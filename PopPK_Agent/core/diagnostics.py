"""
诊断图生成与AI判读管道

负责:
- 调用R脚本生成GOF图、VPC图、个体拟合图
- 调用AI视觉模型判读诊断图
- 生成Markdown审计报告
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DiagnosticsPipeline:
    """诊断图生成与AI判读管道"""

    def __init__(self, config, llm_backend, rule_engine, nonmem_runner):
        self.config = config
        self.llm = llm_backend
        self.rules = rule_engine
        self.runner = nonmem_runner
        self.workspace = Path(config.workspace_dir)

    def run_full_diagnostics(self, run_id: int, prev_run_id: Optional[int] = None, run_vpc: bool = True) -> Dict:
        """
        执行完整诊断流程

        1. 生成诊断图 (R脚本)
        2. AI判读GOF图
        3. AI判读VPC图 (如果运行了VPC)
        4. 汇总诊断报告

        Returns:
            诊断结果字典
        """
        results = {
            "run_id": run_id,
            "prev_run_id": prev_run_id,
            "plot_generation": {},
            "gof_audit": None,
            "vpc_audit": None,
            "summary": "",
        }

        # 1. 生成诊断图
        logger.info(f"[诊断] 开始生成 Run {run_id} 的诊断图...")
        plot_results = self.runner.generate_all_diagnostics(run_id, run_vpc=run_vpc)
        results["plot_generation"] = plot_results

        # 2. AI判读GOF图
        gof_path = self.workspace / f"GOF_mod{run_id}.jpg"
        if gof_path.exists():
            logger.info(f"[诊断] AI判读GOF图...")
            prev_gof_path = None
            if prev_run_id:
                prev_gof = self.workspace / f"GOF_mod{prev_run_id}.jpg"
                if prev_gof.exists():
                    prev_gof_path = str(prev_gof)

            results["gof_audit"] = self.audit_gof(run_id, str(gof_path), prev_gof_path)
        else:
            logger.warning(f"GOF图不存在: {gof_path}")
            results["gof_audit"] = {"error": "GOF图未生成"}

        # 3. AI判读VPC图
        if run_vpc:
            vpc_path = self.workspace / f"VPC_Stratified_mod{run_id}.jpg"
            if not vpc_path.exists():
                vpc_path = self.workspace / f"VPC_mod{run_id}.jpg"

            if vpc_path.exists():
                logger.info(f"[诊断] AI判读VPC图...")
                prev_vpc_path = None
                if prev_run_id:
                    prev_vpc = self.workspace / f"VPC_mod{prev_run_id}.jpg"
                    if prev_vpc.exists():
                        prev_vpc_path = str(prev_vpc)

                results["vpc_audit"] = self.audit_vpc(run_id, str(vpc_path), prev_vpc_path)
            else:
                logger.warning(f"VPC图不存在: {vpc_path}")
                results["vpc_audit"] = {"error": "VPC图未生成"}

        # 4. 汇总报告
        results["summary"] = self._generate_summary(results)

        return results

    def audit_gof(self, run_id: int, gof_image: str, prev_gof_image: Optional[str] = None) -> Dict:
        """AI判读GOF诊断图"""
        rules_text = self.rules.format_for_prompt(namespaces=["@ModelEvaluation"])

        image_list = [gof_image]
        if prev_gof_image:
            image_list.append(prev_gof_image)

        prompt = f"""
你是一名资深的群体药理学视觉诊断专家。请对提供的 GOF (Goodness-of-Fit) 诊断图进行系统性审计。

### 流程 1: 子图识别
请先识别图片中包含的子图类型（如 DV vs PRED, DV vs IPRED, CWRES vs Time, |IWRES vs IPRED|, QQ-plot 等）。

### 流程 2: 规则匹配与评价
参考下方的规则库，针对识别出的子图进行趋势、偏倚和异常点的深度辨析。

### 规则库
{rules_text}

### 流程 3: 演进对比
{"如果提供了前序模型图，请对比两者的拟合改善情况。" if prev_gof_image else "这是首次审计，无前序模型对比。"}

### 输出要求
1. 引用 Rule ID 给出判定意见
2. 识别具体问题（如有）
3. 给出优化建议
4. 输出 Markdown 格式

请分析当前模型 (Run {run_id}){"，并与前序模型 (Run " + str(prev_gof_image and "previous") + ") 对比" if prev_gof_image else ""}。
"""

        try:
            report = self.llm.vision(prompt, image_list)
            return {
                "success": True,
                "report": report,
                "image": gof_image,
            }
        except Exception as e:
            logger.error(f"GOF视觉审计失败: {e}")
            return {"success": False, "error": str(e)}

    def audit_vpc(self, run_id: int, vpc_image: str, prev_vpc_image: Optional[str] = None) -> Dict:
        """AI判读VPC诊断图"""
        rules_text = self.rules.format_for_prompt(namespaces=["@ModelEvaluation"])

        image_list = [vpc_image]
        if prev_vpc_image:
            image_list.append(prev_vpc_image)

        prompt = f"""
你是一名顶级的群体药理学模型验证专家。请对提供的 VPC (Visual Predictive Check) 诊断图进行深度审计。

### 规则库
{rules_text}

### 任务 1: 图像特征识别
识别图片中的分位数线（Observed 5th, 50th, 95th）与模拟预测区间（PI, Shaded areas）。

### 任务 2: 覆盖度评估
- 中位数预测: 观测中位线是否落在模拟预测区间内？
- 变异度预测: 5% 和 95% 分位数线的覆盖是否合理？
- 分布对称性: 模拟区间是否平衡地包裹了观测数据？

### 任务 3: 演进对比
{"对比当前模型与前序模型的VPC表现改善情况。" if prev_vpc_image else "这是首次VPC审计。"}

### 任务 4: 规则化评价
引用 Rule ID (重点关注 ME-VALID-002) 评价预测性能。

### 结论
给出模型是否达到QC定稿要求的最终意见。输出 Markdown 格式。
当前模型: Run {run_id}。
"""

        try:
            report = self.llm.vision(prompt, image_list)
            return {
                "success": True,
                "report": report,
                "image": vpc_image,
            }
        except Exception as e:
            logger.error(f"VPC视觉审计失败: {e}")
            return {"success": False, "error": str(e)}

    def _generate_summary(self, results: Dict) -> str:
        """生成诊断汇总"""
        lines = [f"=== Run {results['run_id']} 诊断汇总 ===\n"]

        # GOF结果
        gof = results.get("gof_audit", {})
        if gof and gof.get("success"):
            lines.append("**GOF审计**: 完成")
            lines.append(gof["report"][:500] + "...\n" if len(gof.get("report", "")) > 500 else gof.get("report", "") + "\n")
        elif gof and gof.get("error"):
            lines.append(f"**GOF审计**: 失败 ({gof['error']})\n")

        # VPC结果
        vpc = results.get("vpc_audit", {})
        if vpc and vpc.get("success"):
            lines.append("**VPC审计**: 完成")
            lines.append(vpc["report"][:500] + "...\n" if len(vpc.get("report", "")) > 500 else vpc.get("report", "") + "\n")
        elif vpc and vpc.get("error"):
            lines.append(f"**VPC审计**: 失败 ({vpc['error']})\n")

        return "\n".join(lines)

    def save_report(self, run_id: int, results: Dict, output_dir: Optional[str] = None):
        """保存诊断报告"""
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")

        out_dir = Path(output_dir) if output_dir else self.workspace
        out_dir.mkdir(parents=True, exist_ok=True)

        report_path = out_dir / f"Diagnostics_Report_Run{run_id}_{date_str}.md"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"# PopPK 诊断报告 - Run {run_id}\n\n")
            f.write(f"- 生成日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            if results.get("prev_run_id"):
                f.write(f"- 前序模型: Run {results['prev_run_id']}\n")
            f.write(f"\n---\n\n")

            # GOF
            gof = results.get("gof_audit", {})
            if gof and gof.get("success"):
                f.write("## GOF 诊断图审计\n\n")
                f.write(gof["report"])
                f.write("\n\n---\n\n")

            # VPC
            vpc = results.get("vpc_audit", {})
            if vpc and vpc.get("success"):
                f.write("## VPC 诊断图审计\n\n")
                f.write(vpc["report"])
                f.write("\n\n---\n\n")

            f.write("## 诊断汇总\n\n")
            f.write(results.get("summary", ""))

        logger.info(f"诊断报告已保存: {report_path}")
        return report_path
