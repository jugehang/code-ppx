"""
PopPK 自动化建模主循环

核心工作流:
1. 数据特征分析 → AI选择最简模型结构
2. 生成NONMEM控制流 (.mod)
3. 运行NONMEM拟合
4. 解析LST输出
5. 如果运行失败 → AI诊断错误 → 修复 → 回到步骤3
6. 如果运行成功 → 生成诊断图 (GOF/VPC/个体图)
7. AI判读诊断图 → 评估模型表现
8. 如果模型已达标 → 定稿
9. 如果未达标 → AI给出优化建议 → 回到步骤2
10. 循环直到达标或达到最大迭代次数
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

from .config import PopPKConfig
from .llm_backend import create_llm_backend
from .rule_engine import RuleEngine
from .lst_parser import LSTParser
from .model_generator import ModelGenerator
from .nonmem_runner import NonmemRunner
from .diagnostics import DiagnosticsPipeline

from ..agents.model_selector import ModelSelector
from ..agents.error_diagnostician import ErrorDiagnostician
from ..agents.optimization_advisor import OptimizationAdvisor

logger = logging.getLogger(__name__)


class PopPKAutomationLoop:
    """PopPK自动化建模主循环"""

    def __init__(self, workspace_dir: str = "."):
        """初始化自动化引擎"""
        # 加载配置
        self.config = PopPKConfig.load(workspace_dir)

        # 初始化各模块
        self.llm = create_llm_backend(self.config.llm)
        self.rules = RuleEngine(str(self.config.get_rules_path()))
        self.lst_parser = LSTParser()
        self.model_generator = ModelGenerator(self.config, self.llm, self.rules)
        self.runner = NonmemRunner(self.config)
        self.diagnostics = DiagnosticsPipeline(self.config, self.llm, self.rules, self.runner)

        # 初始化AI智能体
        self.model_selector = ModelSelector(self.llm, self.rules)
        self.error_diagnostician = ErrorDiagnostician(self.llm, self.rules)
        self.optimization_advisor = OptimizationAdvisor(self.llm, self.rules)

        # 运行历史
        self.history: list = []
        self.start_run_id = 1  # 起始模型编号

    def run(self, start_run_id: int = 1, max_iterations: int = None, run_vpc: bool = True) -> Dict:
        """
        启动自动化建模循环

        Args:
            start_run_id: 起始模型编号
            max_iterations: 最大迭代次数
            run_vpc: 是否在每次迭代中运行VPC

        Returns:
            最终结果汇总
        """
        max_iter = max_iterations or self.config.max_iterations
        self.start_run_id = start_run_id
        current_run_id = start_run_id
        prev_run_id = None
        prev_ofv = None
        iteration = 0

        print(f"\n{'#' * 70}")
        print(f"#  PopPK 自动化建模引擎启动")
        print(f"#  项目: {self.config.project.project_name}")
        print(f"#  药物: {self.config.project.drug_type}")
        print(f"#  最大迭代: {max_iter}")
        print(f"#  LLM后端: {self.config.llm.backend} ({self.config.llm.model_id})")
        print(f"{'#' * 70}\n")

        # Step 0: 数据分析
        data_path = str(self.config.get_data_path())
        logger.info(f"[Step 0] 分析数据: {data_path}")

        data_columns = ModelGenerator.extract_data_columns(data_path)
        data_summary = ModelGenerator.summarize_data(data_path)

        logger.info(f"数据列: {data_columns}")
        logger.info(f"数据摘要: {data_summary}")

        # Step 1: AI选择初始模型结构
        logger.info("[Step 1] AI选择初始模型结构...")
        model_decision = self.model_selector.select(data_summary, data_columns)
        logger.info(f"模型选择: {model_decision.advan} {model_decision.trans} "
                     f"({'TMDD' if model_decision.has_tmdd else '线性'}) "
                     f"误差: {model_decision.error_model}")
        logger.info(f"选择理由: {model_decision.reasoning}")

        optimization_hint = None

        # 主循环
        while iteration < max_iter:
            iteration += 1
            current_run_id = start_run_id + iteration - 1

            print(f"\n{'=' * 70}")
            print(f"  迭代 #{iteration} | Run {current_run_id}")
            print(f"{'=' * 70}")

            # Step 2: 生成控制流
            logger.info(f"[Step 2.{iteration}] 生成NONMEM控制流...")

            prev_result_dict = None
            if prev_run_id:
                prev_result_dict = self._get_prev_result_dict(prev_run_id, prev_ofv)

            mod_content = self.model_generator.generate_model(
                run_id=current_run_id,
                data_columns=data_columns,
                data_summary=data_summary,
                prev_result=prev_result_dict,
                optimization_hint=optimization_hint,
            )

            mod_path = self.model_generator.save_mod_file(current_run_id, mod_content)
            logger.info(f"控制流已保存: {mod_path}")

            # Step 3: 运行NONMEM
            logger.info(f"[Step 3.{iteration}] 运行NONMEM...")
            nm_success, nm_log = self.runner.run_nonmem(current_run_id)

            if not nm_success:
                # Step 4a: 运行失败 → 诊断错误
                logger.error(f"NONMEM运行失败，启动错误诊断...")

                lst_path = self.config.workspace_dir and Path(self.config.workspace_dir) / f"run{current_run_id}.lst"
                if lst_path and lst_path.exists():
                    lst_result = self.lst_parser.parse(str(lst_path), current_run_id)
                else:
                    lst_result = self._parse_failed_result(current_run_id, nm_log)

                diagnosis = self.error_diagnostician.diagnose(
                    lst_content=lst_result.raw_text or nm_log,
                    mod_content=mod_content,
                    error_messages=lst_result.error_messages or [nm_log],
                    warnings=lst_result.warnings,
                )

                logger.warning(f"错误类型: {diagnosis.error_type}")
                logger.warning(f"根本原因: {diagnosis.root_cause}")
                logger.warning(f"修复建议: {diagnosis.fix_suggestion}")

                # 记录历史
                self.history.append({
                    "run_id": current_run_id,
                    "iteration": iteration,
                    "status": "failed",
                    "diagnosis": diagnosis.__dict__,
                    "ofv": None,
                })

                # 使用诊断建议作为下一次优化的hint
                optimization_hint = f"""
模型运行失败，需要修复:
- 错误类型: {diagnosis.error_type}
- 原因: {diagnosis.root_cause}
- 修复: {diagnosis.fix_suggestion}
请基于此修复建议调整模型。
"""
                prev_run_id = current_run_id
                continue

            # Step 4: 运行成功 → 解析LST
            logger.info(f"[Step 4.{iteration}] 解析LST输出...")
            lst_path = Path(self.config.workspace_dir) / f"run{current_run_id}.lst"
            lst_result = self.lst_parser.parse(str(lst_path), current_run_id)

            summary = self.lst_parser.format_summary(lst_result)
            print(summary)

            if lst_result.ofv is None:
                logger.error("无法提取OFV，可能模型运行异常")
                optimization_hint = "模型运行异常，OFV无法提取，请检查模型结构"
                prev_run_id = current_run_id
                continue

            # Step 5: 生成诊断图
            logger.info(f"[Step 5.{iteration}] 生成诊断图...")
            # 前几次迭代跳过VPC（耗时），最后一次或定稿前运行VPC
            should_run_vpc = run_vpc and (iteration >= max_iter - 1 or iteration % 3 == 0)

            diag_results = self.diagnostics.run_full_diagnostics(
                run_id=current_run_id,
                prev_run_id=prev_run_id,
                run_vpc=should_run_vpc,
            )

            # Step 6: AI评估并决策
            logger.info(f"[Step 6.{iteration}] AI评估模型表现并决策...")

            gof_report = diag_results.get("gof_audit", {}).get("report", "GOF审计未完成")
            vpc_report = diag_results.get("vpc_audit", {}).get("report", "VPC审计未完成")

            decision = self.optimization_advisor.evaluate_and_advise(
                run_result={
                    "ofv": lst_result.ofv,
                    "final_estimates": lst_result.final_estimates,
                    "shrinkage_summary": self._format_shrinkage(lst_result),
                    "warnings": lst_result.warnings,
                    "control_stream": lst_result.control_stream,
                },
                gof_report=gof_report,
                vpc_report=vpc_report,
                prev_ofv=prev_ofv,
                iteration=iteration,
            )

            print(f"\n--- AI决策 (迭代 #{iteration}) ---")
            print(f"动作: {decision.action}")
            print(f"方向: {decision.direction}")
            print(f"置信度: {decision.confidence:.0%}")
            print(f"建议: {decision.suggestion}")

            # 记录历史
            self.history.append({
                "run_id": current_run_id,
                "iteration": iteration,
                "status": "success",
                "ofv": lst_result.ofv,
                "decision": decision.action,
                "confidence": decision.confidence,
                "gof_report": gof_report[:500],
                "vpc_report": vpc_report[:500],
            })

            # Step 7: 判断是否结束
            if decision.action == "finalize" or decision.is_final:
                logger.info("AI判定模型已达标，建议定稿!")
                return self._generate_final_report(current_run_id, iteration)

            elif decision.action == "stop":
                logger.warning("AI建议停止迭代")
                return self._generate_final_report(current_run_id, iteration, stopped=True)

            # 继续优化
            optimization_hint = decision.suggestion
            prev_run_id = current_run_id
            prev_ofv = lst_result.ofv

        # 达到最大迭代次数
        logger.warning(f"达到最大迭代次数 ({max_iter})")
        return self._generate_final_report(current_run_id, iteration, max_reached=True)

    def _get_prev_result_dict(self, prev_run_id: int, prev_ofv: Optional[float]) -> Dict:
        """获取前序模型结果字典"""
        lst_path = Path(self.config.workspace_dir) / f"run{prev_run_id}.lst"
        if lst_path.exists():
            result = self.lst_parser.parse(str(lst_path), prev_run_id)
            return {
                "control_stream": result.control_stream,
                "ofv": result.ofv,
                "final_estimates": result.final_estimates,
                "shrinkage_summary": self._format_shrinkage(result),
                "warnings": result.warnings,
            }
        return {}

    @staticmethod
    def _format_shrinkage(result) -> str:
        """格式化收缩率摘要"""
        if not result.shrinkage:
            return "N/A"
        parts = []
        for key, val in result.shrinkage.eta_shrink_sd.items():
            parts.append(f"{key}: {val:.2f}%")
        return ", ".join(parts) if parts else "N/A"

    def _parse_failed_result(self, run_id: int, log: str):
        """构造运行失败的解析结果"""
        from .lst_parser import ModelRunResult
        return ModelRunResult(
            run_id=run_id,
            success=False,
            raw_text=log,
            error_messages=[log[:1000]],
        )

    def _generate_final_report(self, final_run_id: int, iterations: int,
                                stopped: bool = False, max_reached: bool = False) -> Dict:
        """生成最终报告"""
        date_str = datetime.now().strftime("%Y%m%d")

        # 保存运行历史
        history_path = Path(self.config.workspace_dir) / f"automation_history_{date_str}.json"
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False, default=str)

        # 汇总
        successful_runs = [h for h in self.history if h["status"] == "success"]
        failed_runs = [h for h in self.history if h["status"] == "failed"]

        status = "完成" if not (stopped or max_reached) else ("停止" if stopped else "达到最大迭代")

        report = {
            "status": status,
            "final_run_id": final_run_id,
            "total_iterations": iterations,
            "successful_runs": len(successful_runs),
            "failed_runs": len(failed_runs),
            "history_file": str(history_path),
            "history": self.history,
        }

        print(f"\n{'#' * 70}")
        print(f"#  自动化建模 {status}")
        print(f"#  最终模型: Run {final_run_id}")
        print(f"#  总迭代: {iterations} (成功: {len(successful_runs)}, 失败: {len(failed_runs)})")
        print(f"#  历史记录: {history_path}")
        print(f"{'#' * 70}\n")

        return report


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="PopPK自动化建模引擎")
    parser.add_argument("--workspace", "-w", default=".", help="工作目录")
    parser.add_argument("--start-id", "-s", type=int, default=1, help="起始模型编号")
    parser.add_argument("--max-iter", "-m", type=int, default=20, help="最大迭代次数")
    parser.add_argument("--no-vpc", action="store_true", help="跳过VPC (加速迭代)")
    parser.add_argument("--log-level", default="INFO", help="日志级别")

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    loop = PopPKAutomationLoop(args.workspace)
    result = loop.run(
        start_run_id=args.start_id,
        max_iterations=args.max_iter,
        run_vpc=not args.no_vpc,
    )

    return result


if __name__ == "__main__":
    main()
