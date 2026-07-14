import re
import json
import logging
from pathlib import Path
from typing import Dict, Any
from openai import OpenAI

# =================================================================
# 1. 全局配置区
# =================================================================
CONFIG = {
    "LM_STUDIO_URL": "http://localhost:1234/v1",
    "MODEL_ID": "google/gemma-4-26b-a4b",
    "PREV_MODEL": "run38.lst",
    "CURR_MODEL": "run41.lst",
    "DRUG_TYPE": "Monoclonal Antibody (mAb)",
    "LOG_LEVEL": logging.INFO
}

# =================================================================
# 2. 初始化与日志
# =================================================================
logging.basicConfig(level=CONFIG["LOG_LEVEL"], format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

client = OpenAI(base_url=CONFIG["LM_STUDIO_URL"], api_key="lm-studio")


class PopPKExpertV16:
    """
    PopPK 专家审计系统 V16
    修复了 f-string 格式化 None 对象的 Bug，增强了字段提取的容错性
    """

    def __init__(self, model_id: str):
        self.model_id = model_id

    def _get_key_blocks(self, file_path: Path) -> str:
        """提取 LST 核心文本块，确保包含 $PK, $THETA, $OMEGA, $SIGMA 和 Shrinkage"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # 1. 控制流
            ctrl_match = re.search(r"(\$PROBLEM[\s\S]*?)(?=\$EST)", content)
            control_block = ctrl_match.group(0) if ctrl_match else "未找到控制流"

            # 2. Shrinkage 统计块
            shrink_block = ""
            shrink_match = re.search(r"(ETABAR:[\s\S]*?EPSSHRINKVR.*)", content)
            if shrink_match:
                shrink_block = "\n[SHRINKAGE & ETABAR STATS]\n" + shrink_match.group(0)

            # 3. 结果矩阵
            res_match = re.search(r"FINAL PARAMETER ESTIMATE[\s\S]*", content)
            results_block = res_match.group(0)[:9500] if res_match else "未找到结果数据"

            # 4. OFV
            ofv_line = ""
            ofv_match = re.search(r"#OBJV:.*", content)
            if ofv_match:
                ofv_line = ofv_match.group(0)

            return f"\n--- 文件: {file_path.name} ---\n{ofv_line}\n\n[控制流指令]\n{control_block}\n{shrink_block}\n\n[最终估算结果]\n{results_block}"
        except Exception as e:
            return f"读取 {file_path} 失败: {str(e)}"

    def extract_with_ai(self, file_path: Path) -> Dict:
        """调用 AI 作为顶级 PopPK 专家进行语义化解析"""
        raw_text = self._get_key_blocks(file_path)

        prompt = f"""
        你是一名顶级的群体药动学 (PopPK) 专家，尤其擅长单克隆抗体 (mAb) 建模。
        请解析以下 NONMEM 文本，并严格以 JSON 格式输出。

        【提取要求】
        1. 结构识别：记录模型几室、有无异速生长协变量。
        2. 参数映射：根据 $PK 注释确定 Theta 名 (如 CL, V1, Q, V2, V1WT 等)。
        3. Theta/IIV 对：提取 Estimate, RSE, IIV CV%, 和 ETASHRINKSD。
        4. 残差 (SIGMA)：提取 Estimate, RSE, 和 EPSSHRINKSD。
        5. OFV：目标函数值。

        【注意】若某项不存在或为 FIXED，请在 JSON 中显式写为 "FIXED" 或 "N/A"，不要留 null。

        文本数据：
        {raw_text}

        输出格式：
        {{
          "filename": "{file_path.name}",
          "structure": "描述",
          "ofv": 0.0,
          "params": [
            {{"name": "CL", "theta": 0.0, "rse": "x%", "iiv_cv": "x%", "iiv_shrink": "x%"}}
          ],
          "residuals": [
            {{"name": "Sigma11", "estimate": 0.0, "rse": "x%", "eps_shrink": "x%"}}
          ]
        }}
        """

        try:
            response = client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            clean_json = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
            return json.loads(clean_json)
        except Exception as e:
            logger.error(f"AI 解析 {file_path.name} 失败: {e}")
            return {"filename": file_path.name, "params": [], "residuals": [], "ofv": 0}

    def audit_comparison(self, data_prev: Dict, data_curr: Dict) -> str:
        """深度审计两个模型的演进"""
        d_ofv = round(data_curr.get('ofv', 0) - data_prev.get('ofv', 0), 3)
        prompt = f"""
        你是定量药理学导师。请对比分析以下两个模型。run41 是在 run38 基础上引入体重协变量的最终模型。

        ΔOFV: {d_ofv}
        run41 结构: {data_curr.get('structure')}

        详细数据:
        Theta/IIV: {json.dumps(data_curr['params'], ensure_ascii=False)}
        Residuals: {json.dumps(data_curr['residuals'], ensure_ascii=False)}

        请针对单抗特性评价 Vc 估计值、权重协变量的贡献、以及残差和收缩率的稳定性。
        最后给出 QC 结论是否建议定稿。
        """
        try:
            response = client.chat.completions.create(model=self.model_id,
                                                      messages=[{"role": "user", "content": prompt}], temperature=0.2)
            return response.choices[0].message.content
        except Exception as e:
            return f"审计生成失败: {e}"


# =================================================================
# 3. 运行工作流
# =================================================================
def start_audit_session():
    agent = PopPKExpertV16(CONFIG["MODEL_ID"])

    report_prev = agent.extract_with_ai(Path(CONFIG["PREV_MODEL"]))
    report_curr = agent.extract_with_ai(Path(CONFIG["CURR_MODEL"]))

    print("\n" + "📊" * 5 + f" PopPK 模型全参数对比审计表 ({CONFIG['PREV_MODEL']} -> {CONFIG['CURR_MODEL']}) " + "📊" * 5)
    print(f"结构描述: {report_curr.get('structure', 'N/A')}")

    # --- A. Theta & IIV 对比表 (增加了 str() 转换防止 None 错误) ---
    t_header = f"{'Parameter':<15} | {'Prev (Est/RSE)':<25} | {'Curr (Est/RSE)':<25} | {'IIV CV%':<12} | {'IIV Shrink'}"
    print("-" * len(t_header))
    print(t_header)
    print("-" * len(t_header))

    prev_lookup = {p['name']: p for p in report_prev.get('params', [])}
    for curr_p in report_curr.get('params', []):
        name = str(curr_p.get('name') or '-')
        prev_p = prev_lookup.get(name, {})

        # 强制转换为字符串进行 padding
        p_est = str(prev_p.get('theta') or '-')
        p_rse = str(prev_p.get('rse') or '-')
        c_est = str(curr_p.get('theta') or '-')
        c_rse = str(curr_p.get('rse') or '-')

        p_str = f"{p_est} ({p_rse})"
        c_str = f"{c_est} ({c_rse})"

        iiv_cv = str(curr_p.get('iiv_cv') or '-')
        iiv_sh = str(curr_p.get('iiv_shrink') or '-')

        print(f"{name:<15} | {p_str:<25} | {c_str:<25} | {iiv_cv:<12} | {iiv_sh}")

    # --- B. Residual Error 表 (同步增加 str() 转换) ---
    print("-" * len(t_header))
    print(f"{'Residual Error':<15} | {'Estimate':<25} | {'RSE%':<25} | {'EPS Shrink':<12}")
    for res in report_curr.get('residuals', []):
        r_name = str(res.get('name') or 'Sigma')
        r_est = str(res.get('estimate') or '-')
        r_se = str(res.get('rse') or '-')
        r_sh = str(res.get('eps_shrink') or '-')
        print(f"{r_name:<15} | {r_est:<25} | {r_se:<25} | {r_sh:<12}")

    print("-" * len(t_header))
    d_ofv = round(report_curr.get('ofv', 0) - report_prev.get('ofv', 0), 3)
    print(f"OFV 汇总: 前序={report_prev.get('ofv')} | 当前={report_curr.get('ofv')} | ΔOFV={d_ofv}")

    # --- C. 专家审计 ---
    print("\n" + "🧠" * 10 + " PopPK 专家深度审计报告 " + "🧠" * 10)
    print(agent.audit_comparison(report_prev, report_curr))


if __name__ == "__main__":
    try:
        start_audit_session()
    except Exception as e:
        logger.error(f"审计会话异常: {e}", exc_info=True)