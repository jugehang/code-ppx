import re
import json
import logging
import subprocess
import pandas as pd
from pathlib import Path
from datetime import datetime
from openai import OpenAI

# =================================================================
# 1. 全局配置区
# =================================================================
CONFIG = {
    "LM_STUDIO_URL": "http://localhost:1234/v1",
    "MODEL_ID": "google/gemma-4-26b-a4b",
    "PREV_INDEX": "38",  # 前序模型 (Previous)
    "CURR_INDEX": "41",  # 当前模型 (Current)
    "R_SCRIPT_NAME": "pk parameters script.R",
    "RULES_FILE": "poppk_rules.json",
    "LOG_LEVEL": logging.INFO
}

# --- 自动路径生成逻辑 ---
# 格式: Compare[前序]-[当前]-[日期]
DATE_STR = datetime.now().strftime("%Y%m%d")
FOLDER_NAME = f"Compare{CONFIG['PREV_INDEX']}-{CONFIG['CURR_INDEX']}-{DATE_STR}"
OUTPUT_PATH = Path(FOLDER_NAME)

# 创建归档文件夹
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

# 日志配置
logging.basicConfig(
    level=CONFIG["LOG_LEVEL"],
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化 OpenAI 客户端
client = OpenAI(base_url=CONFIG["LM_STUDIO_URL"], api_key="lm-studio")


class PopPKMasterAuditorV28:
    """
    PopPK 专家审计系统 V28
    功能：路径自动归档 + 规则库盲审 + 原始 LST 深度对账 + Markdown 报告生成
    """

    def __init__(self, model_id: str, rules_path: str):
        self.model_id = model_id
        self.rules_json = self._load_rules(rules_path)

    def _load_rules(self, path):
        """加载 poppk_rules.json 知识库"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"规则库加载失败，将使用内置基础准则: {e}")
            return "内置准则：RSE < 30%, Shrinkage < 30%, mAb Vc 3-5L"

    def run_r_engine(self, idx: str):
        """调用 R 脚本产生参数表，并将生成的 CSV 移动到输出目录"""
        try:
            logger.info(f"正在启动 R 引擎处理 Run {idx}...")
            # 执行 R 脚本 (传入编号作为参数)
            subprocess.run(["Rscript", CONFIG["R_SCRIPT_NAME"], idx], check=True, capture_output=True)

            csv_name = f"data_run{idx}.csv"
            if Path(csv_name).exists():
                df = pd.read_csv(csv_name)
                # 将 CSV 移动到目标文件夹进行备份
                Path(csv_name).replace(OUTPUT_PATH / f"raw_data_run{idx}.csv")
                return df
            else:
                logger.error(f"Run {idx} 的数据 CSV 未找到。")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"Run {idx} R 脚本运行失败: {e}")
            return pd.DataFrame()

    def _get_lst_source_truth(self, idx: str, role_label: str):
        """从 LST 原始文件中提取‘未经加工’的真相"""
        path = f"run{idx}.lst"
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # 1. 提取 OFV 和 AIC (鲁棒正则)
            ofv = re.search(r"(?:OBJV:|MINIMUM VALUE OF OBJECTIVE FUNCTION).*?([\d\.\-]+)", content, re.I)
            aic = re.search(r"AIC.*?([\d\.\-]+)", content, re.I)

            # 2. 提取估值矩阵和标准误矩阵
            estimates = re.search(r"FINAL PARAMETER ESTIMATE[\s\S]*?(?=\s*1\s*TOTAL)", content)
            se_matrix = re.search(r"STANDARD ERROR OF ESTIMATE[\s\S]*?(?=\s*1\s*TOTAL)", content)

            # 3. 提取收缩率 (Shrinkage)
            shrinkage = re.search(r"(ETABAR:[\s\S]*?EPSSHRINKVR.*)", content)

            # 4. 提取控制流核心逻辑 ($PK 块)
            pk_logic = re.search(r"(\$PK[\s\S]*?)(?=\$ERROR|\$EST)", content)

            return {
                "ofv": ofv.group(1) if ofv else "N/A",
                "aic": aic.group(1) if aic else "N/A",
                "summary": f"### [{role_label} (Run {idx}) 原始真相提取] ###\n"
                           f"Objective Function Value: {ofv.group(1) if ofv else 'N/A'}\n"
                           f"AIC: {aic.group(1) if aic else 'N/A'}\n"
                           f"Control Stream ($PK): \n{pk_logic.group(0) if pk_logic else 'N/A'}\n"
                           f"Estimate Matrix: \n{estimates.group(0) if estimates else 'N/A'}\n"
                           f"Standard Error Matrix: \n{se_matrix.group(0) if se_matrix else 'N/A'}\n"
                           f"Shrinkage Table: \n{shrinkage.group(0) if shrinkage else 'N/A'}"
            }
        except Exception as e:
            logger.error(f"解析 {path} 失败: {e}")
            return {"ofv": "N/A", "summary": f"读取 LST 失败: {str(e)}"}

    def start_automated_session(self):
        """核心工作流：R 出表 -> LST 提取 -> AI 盲审 -> 归档"""

        # 1. R 脚本产出
        df_prev_r = self.run_r_engine(CONFIG["PREV_INDEX"])
        df_curr_r = self.run_r_engine(CONFIG["CURR_INDEX"])

        # 2. LST 源码真相提取
        prev_data = self._get_lst_source_truth(CONFIG["PREV_INDEX"], "前序模型")
        curr_data = self._get_lst_source_truth(CONFIG["CURR_INDEX"], "当前模型")

        # 3. 构造盲审 Prompt
        prompt = f"""
        你是一名顶级的群体药动学/药效学 (PopPK/PD) 审计专家。
        请根据提供的【Rule Library】作为判定标准，对【前序模型】和【当前模型】的演进进行审计。

        --- 判定准则库 (Rule Library) ---
        {self.rules_json}

        --- 任务要求 ---
        请以 Markdown 格式撰写报告，严格执行以下逻辑：

        1. 模型发现 (Discovery)：
           - 对比 $PK 逻辑，自主识别当前模型做了哪些改动。不要预设答案。
        2. 数据对账 (Audit)：
           - 核对当前模型 Estimates/SE Matrix 与下表（R 脚本产出）是否一致。识别是否存在“数值位移”或提取错误。
        3. 规则化评价 (Evaluation)：
           - 统计学：计算 ΔOFV/ΔAIC。引用 Rule ID (如 ME-COMP-001) 判定显著性。
           - 精度与收缩率：根据准则库评价 RSE 和 Shrinkage 是否在接受限度内。
           - 生理意义：评价主参数（如单抗 Vc）的演进是否更符合生理。
        4. 最终判定：是否建议定稿。

        --- R 脚本输出的 CSV 预览 (用于 Check) ---
        {df_curr_r.to_markdown(index=False) if not df_curr_r.empty else "R 脚本未输出有效数据"}

        --- 审计底稿：原始 LST 文本 ---
        {prev_data['summary']}
        {curr_data['summary']}
        """

        logger.info("AI 审计员正在分析演进逻辑并撰写报告...")

        try:
            response = client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            report_md = response.choices[0].message.content

            # 4. 保存报告与移动文件
            self._archive_results(df_prev_r, df_curr_r, prev_data, curr_data, report_md)

        except Exception as e:
            logger.error(f"审计流程中断: {e}")

    def _archive_results(self, dp, dc, tp, tc, report_md):
        """保存 Markdown 报告、备份 Excel 并移动 R 生成的 Word 文档"""

        # 1. 保存 Markdown 报告
        report_name = f"Audit_Report_Run{CONFIG['CURR_INDEX']}_{DATE_STR}.md"
        with open(OUTPUT_PATH / report_name, "w", encoding="utf-8") as f:
            f.write(f"# PopPK 模型演进审计报告\n\n")
            f.write(f"- **前序**: Run {CONFIG['PREV_INDEX']} | **当前**: Run {CONFIG['CURR_INDEX']}\n")
            f.write(f"- **生成路径**: `{OUTPUT_PATH.absolute()}`\n\n---\n\n")
            f.write(report_md)

        logger.info(f"Markdown 报告已生成: {report_name}")

        # 2. 移动 R 脚本生成的 Word 表格 (如果存在)
        for idx in [CONFIG["PREV_INDEX"], CONFIG["CURR_INDEX"]]:
            word_file = f"Table5_Run{idx}_Final_Parameters.docx"  # 根据你 R 脚本定义的输出名
            if Path(word_file).exists():
                Path(word_file).replace(OUTPUT_PATH / word_file)

        # 3. 备份一个统计汇总 Excel
        summary_excel = OUTPUT_PATH / "Statistical_Summary.xlsx"
        with pd.ExcelWriter(summary_excel, engine='openpyxl') as writer:
            # 统计汇总
            stats = pd.DataFrame({
                "Model": ["Previous", "Current", "Difference"],
                "OFV": [tp['ofv'], tc['ofv'],
                        round(float(tc['ofv']) - float(tp['ofv']), 3) if tc['ofv'] != "N/A" and tp[
                            'ofv'] != "N/A" else "N/A"]
            })
            stats.to_excel(writer, sheet_name="OFV_Comparison", index=False)
            # 导出当前模型的 R 提取原文
            dc.to_excel(writer, sheet_name="Current_Model_Data", index=False)

        print("\n" + "🛡️" * 5 + " 审计工作流全部完成 " + "🛡️" * 5)
        print(f"📁 所有分析结果已妥善存放到文件夹: {OUTPUT_PATH}")
        print(f"📄 专家解读请阅读: {report_name}")


if __name__ == "__main__":
    # 实例化并运行
    auditor = PopPKMasterAuditorV28(
        model_id=CONFIG["MODEL_ID"],
        rules_path=CONFIG["RULES_FILE"]
    )

    auditor.start_automated_session()