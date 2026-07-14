import base64
import logging
import shutil
from pathlib import Path
from datetime import datetime
from openai import OpenAI

# =================================================================
# 1. 配置区 (请根据实际情况调整模型编号)
# =================================================================
CONFIG = {
    "LM_STUDIO_URL": "http://localhost:1234/v1",
    "MODEL_ID": "google/gemma-4-26b-a4b",  # 请确认该模型支持 Vision/多模态
    "PREV_INDEX": "38",
    "CURR_INDEX": "41",
    "RULES_FILE": "poppk_rules.json",
    "LOG_LEVEL": logging.INFO
}

# --- 自动路径管理 ---
DATE_STR = datetime.now().strftime("%Y%m%d")
FOLDER_NAME = f"Compare{CONFIG['PREV_INDEX']}-{CONFIG['CURR_INDEX']}-{DATE_STR}"
OUTPUT_PATH = Path(FOLDER_NAME)
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=CONFIG["LOG_LEVEL"], format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化 OpenAI 客户端
client = OpenAI(base_url=CONFIG["LM_STUDIO_URL"], api_key="lm-studio")


class VPCMasterAuditorV35:
    """
    PopPK VPC 演进对比审计专家
    功能：分位数覆盖率深度对比 + 预测区间合理性核对 + 规则库准则比对
    """

    def __init__(self, model_id, rules_path):
        self.model_id = model_id
        self.rules_json = self._load_rules(rules_path)

    def _load_rules(self, path):
        """加载航哥整理的规则库"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"规则库加载失败，将使用默认准则: {e}")
            return "准则：观测值的分位数线(5%, 50%, 95%)应良好地落在模拟预测区间(PI)内。"

    def _encode_image(self, image_path):
        """将图片转为 Base64 编码"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def run_audit(self):
        curr_name = f"VPC_mod{CONFIG['CURR_INDEX']}.jpg"
        prev_name = f"VPC_mod{CONFIG['PREV_INDEX']}.jpg"

        curr_path = Path(curr_name)
        prev_path = Path(prev_name)

        if not curr_path.exists():
            logger.error(f"❌ 错误：在当前目录下找不到 VPC 图片 {curr_name}！")
            return

        # 明确日志：这是 VPC 审计
        logger.info(f"🚀 [VPC 审计启动] 正在执行演进对比: Run {CONFIG['PREV_INDEX']} -> Run {CONFIG['CURR_INDEX']}...")

        curr_b64 = self._encode_image(curr_path)
        prev_b64 = self._encode_image(prev_path) if prev_path.exists() else None

        # --- 针对 VPC 深度定制的对比 Prompt ---
        prompt_content = [
            {
                "type": "text",
                "text": f"""
                你是一名顶级的群体药理学模型验证专家。请对提供的 VPC (Visual Predictive Check) 诊断图进行深度审计。

                ### 判定准则库 (Rule Library)
                {self.rules_json}

                ### 任务 1: 图像特征识别 (VPC Components)
                识别图片中的分位数线（Observed 5th, 50th, 95th）与模拟预测区间（PI, Shaded areas）。

                ### 任务 2: 演进对比审计 (Evolutionary Contrast)
                对比【当前模型】与【前序模型】（下方附件）的 VPC 表现。请回答：
                - **中位数预测 (Median)**: 当前模型的中位线覆盖是否比前序模型更精准？是否存在由于协变量（如体重）加入后，中位线从偏离 PI 区间回归到区间内部的表现？
                - **变异度预测 (Variance/Spread)**: 5% 和 95% 分位数线的覆盖是否有实质性改善？
                - **分布对称性**: 在不同剂量组或浓度区间，模拟区间是否更平衡地包裹了观测数据？

                ### 任务 3: 规则化定性评价
                引用 Rule ID (重点关注 ME-VALID-002 或相关 VPC 准则)，评价当前模型是否在预测性能上达到了 QC 定稿要求。

                ### 结论
                基于视觉审计结论，给出该模型演进是否成功、是否可以定稿的最终意见。
                请直接输出 Markdown 格式。
                """
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{curr_b64}"}
            }
        ]

        if prev_b64:
            prompt_content.append(
                {"type": "text", "text": "【参考附件：前序模型 Run " + CONFIG['PREV_INDEX'] + " 的 VPC 图片】"})
            prompt_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{prev_b64}"}
            })

        # 调用 Vision 接口
        try:
            response = client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt_content}],
                max_tokens=3000
            )
            self._save_report(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"AI 视觉审计请求失败: {e}")

    def _save_report(self, content):
        report_filename = f"VPC_Evolution_Audit_Run{CONFIG['CURR_INDEX']}_{DATE_STR}.md"
        report_path = OUTPUT_PATH / report_filename

        # 1. 保存 Markdown 报告
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# PopPK VPC 预测性能专家审计报告\n\n")
            f.write(f"- **前序**: Run {CONFIG['PREV_INDEX']} | **当前**: Run {CONFIG['CURR_INDEX']}\n")
            f.write(f"- **分析日期**: {datetime.now().strftime('%Y-%m-%d')}\n")
            f.write(f"- **存储路径**: `{OUTPUT_PATH.absolute()}`\n\n---\n\n")
            f.write(content)

        # 2. 安全复制图片（复印原件，不动根目录）
        for idx in [CONFIG['PREV_INDEX'], CONFIG['CURR_INDEX']]:
            img_name = f"VPC_mod{idx}.jpg"
            source = Path(img_name)
            if source.exists():
                shutil.copy2(source, OUTPUT_PATH / img_name)
                logger.info(f"📂 VPC 图片备份已存入文件夹: {img_name}")

        print(f"\n✅ VPC 演进审计完成！")
        print(f"📄 报告已生成: {report_path}")


if __name__ == "__main__":
    auditor = VPCMasterAuditorV35(CONFIG["MODEL_ID"], CONFIG["RULES_FILE"])
    auditor.run_audit()