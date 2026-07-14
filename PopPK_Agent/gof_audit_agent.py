import base64
import logging
import shutil
from pathlib import Path
from datetime import datetime
from openai import OpenAI

# =================================================================
# 1. 配置区
# =================================================================
CONFIG = {
    "LM_STUDIO_URL": "http://localhost:8000/v1",
    "MODEL_ID": "mlx-community/gemma-4-31b-it-4bit",
    "PREV_INDEX": "38",
    "CURR_INDEX": "41",
    "RULES_FILE": "poppk_rules.json",
    "LOG_LEVEL": logging.INFO
}

# 路径管理逻辑
DATE_STR = datetime.now().strftime("%Y%m%d")
FOLDER_NAME = f"Compare{CONFIG['PREV_INDEX']}-{CONFIG['CURR_INDEX']}-{DATE_STR}"
OUTPUT_PATH = Path(FOLDER_NAME)
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=CONFIG["LOG_LEVEL"], format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

client = OpenAI(base_url=CONFIG["LM_STUDIO_URL"], api_key="lm-studio")


class GOFVisualAuditorV31:
    """
    自适应 GOF 审计专家 V31
    优化：使用 copy2 替代 replace，防止源文件丢失导致二次运行失败
    """

    def __init__(self, model_id, rules_path):
        self.model_id = model_id
        self.rules_json = self._load_rules(rules_path)

    def _load_rules(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"规则库加载失败，使用默认准则: {e}")
            return "准则：DV/PRED 应分布在对角线两侧；残差应无趋势且在 ±6 内。"

    def _encode_image(self, image_path):
        """编码图片为 Base64"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def start_audit(self):
        curr_img_name = f"GOF_mod{CONFIG['CURR_INDEX']}.jpg"
        prev_img_name = f"GOF_mod{CONFIG['PREV_INDEX']}.jpg"

        curr_img_path = Path(curr_img_name)
        prev_img_path = Path(prev_img_name)

        # 检查当前模型图片是否存在
        if not curr_img_path.exists():
            logger.error(f"❌ 错误：在当前目录下未找到图片 {curr_img_name}！请确认图片未被移动或删除。")
            return

        logger.info(f"🚀 开启视觉分析流程: {curr_img_name}")

        # 编码图片
        curr_b64 = self._encode_image(curr_img_path)
        prev_b64 = None
        if prev_img_path.exists():
            prev_b64 = self._encode_image(prev_img_path)
            logger.info(f"🔍 找到前序模型图片 {prev_img_name}，将进行对比分析。")
        else:
            logger.warning(f"⚠️ 未找到前序模型图片 {prev_img_name}，将仅对当前模型进行单点审计。")

        # --- 构造视觉 Prompt ---
        prompt_content = [
            {
                "type": "text",
                "text": f"""
                你是一名资深的群体药理学视觉诊断专家。请对提供的 GOF 诊断图进行系统性审计。

                ### 流程 1: 子图识别 (Inventory)
                请先识别图片中包含的子图类型（如 DV vs PRED, DV vs IPRED, CWRES vs Time, |IWRES vs IPRED|, QQ-plot 等）。

                ### 流程 2: 规则匹配与评价
                参考下方的【Rule Library】，针对识别出的子图进行趋势、偏倚和异常点的深度辨析。

                【Rule Library】
                {self.rules_json}

                ### 流程 3: 演进对比 (Evolution)
                如果提供了前序模型图，请对比两者的拟合改善情况。

                ### 结论
                引用 Rule ID 给出判定意见，并输出 Markdown 格式报告。
                """
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{curr_b64}"}
            }
        ]

        if prev_b64:
            prompt_content.append({"type": "text", "text": "【参考附件：前序模型的 GOF 诊断图】"})
            prompt_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{prev_b64}"}
            })

        # 调用 AI 接口
        try:
            response = client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt_content}],
                max_tokens=3000
            )
            self._save_report_and_copy_files(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"AI 审计请求失败: {e}")

    def _save_report_and_copy_files(self, content):
        """保存报告并安全地复制文件（而非移动）"""
        report_name = f"GOF_Expert_Audit_Run{CONFIG['CURR_INDEX']}_{DATE_STR}.md"
        report_path = OUTPUT_PATH / report_name

        # 1. 保存 Markdown 报告
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# PopPK GOF 图像诊断专家审计报告\n\n")
            f.write(f"- **分析对象**: Run {CONFIG['CURR_INDEX']} (对比 Run {CONFIG['PREV_INDEX']})\n")
            f.write(f"- **审计路径**: `{OUTPUT_PATH.absolute()}`\n\n---\n\n")
            f.write(content)

        # 2. 复制图片到文件夹 (使用 shutil.copy2 保证原件不动)
        for idx in [CONFIG["PREV_INDEX"], CONFIG["CURR_INDEX"]]:
            img_name = f"GOF_mod{idx}.jpg"
            source = Path(img_name)
            if source.exists():
                # 复制到目标文件夹，原件依然留在根目录
                shutil.copy2(source, OUTPUT_PATH / img_name)
                logger.info(f"📂 已复制备份: {img_name} -> {OUTPUT_PATH}")

        print(f"\n✅ 视觉审计完成！报告已存档。")
        print(f"📄 报告路径: {report_path}")

if __name__ == "__main__":
    auditor = GOFVisualAuditorV31(CONFIG["MODEL_ID"], CONFIG["RULES_FILE"])
    auditor.start_audit()