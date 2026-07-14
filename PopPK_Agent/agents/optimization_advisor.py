"""
优化建议智能体

AI根据LST解析结果和诊断图审计报告，决定下一步优化方向。
"""

import json
import logging
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OptimizationDecision:
    """优化决策"""
    action: str            # continue | optimize | finalize | stop
    direction: str          # 优化方向描述
    suggestion: str         # 具体建议 (用于生成下一个.mod)
    confidence: float       # 置信度 0-1
    is_final: bool          # 是否已达到可定稿状态


class OptimizationAdvisor:
    """AI优化决策器"""

    def __init__(self, llm_backend, rule_engine):
        self.llm = llm_backend
        self.rules = rule_engine

    def evaluate_and_advise(
        self,
        run_result: Dict,
        gof_report: str,
        vpc_report: str,
        prev_ofv: Optional[float] = None,
        iteration: int = 0,
    ) -> OptimizationDecision:
        """
        评估当前模型并给出优化建议

        Args:
            run_result: LST解析结果
            gof_report: GOF审计报告
            vpc_report: VPC审计报告
            prev_ofv: 前序模型OFV
            iteration: 当前迭代次数

        Returns:
            OptimizationDecision
        """
        eval_rules = self.rules.format_for_prompt(namespaces=["@ModelEvaluation", "@CovariateAnalysis"])

        ofv = run_result.get("ofv")
        d_ofv = (ofv - prev_ofv) if (ofv and prev_ofv) else None

        prompt = f"""
你是顶级的群体药动学(PopPK)建模专家。请评估当前模型的表现，并决定下一步优化方向。

### 当前模型结果 (迭代 #{iteration})
- OFV: {ofv}
- ΔOFV (与前序): {d_ofv}
- 参数估计: {run_result.get('final_estimates', 'N/A')[:2000]}
- 收缩率: {run_result.get('shrinkage_summary', 'N/A')}
- 警告: {run_result.get('warnings', [])}

### GOF审计报告
{gof_report[:3000]}

### VPC审计报告
{vpc_report[:3000]}

### 评估规则参考
{eval_rules}

### 决策要求
请基于以上信息，判断:
1. 当前模型是否已达到可定稿标准? (GOF良好, VPC覆盖合理, 收缩率<30%, RSE<30%)
2. 如果未达标，最大的优化空间在哪里? (协变量/结构模型/误差模型/IIV)
3. 给出具体的优化建议 (可直接用于生成下一个.mod)

### 决策选项
- "continue": 继续优化 (模型表现尚可但仍有改进空间)
- "finalize": 定稿 (模型已达到QC标准)
- "stop": 停止 (无法进一步改进或出现严重问题)

### 输出格式 (严格JSON)
{{
  "action": "continue/finalize/stop",
  "direction": "优化方向简要描述",
  "suggestion": "具体优化建议，包括要修改的参数、结构或协变量",
  "confidence": 0.8,
  "is_final": false
}}
"""

        try:
            result = self.llm.chat_json(prompt)
            return OptimizationDecision(
                action=result.get("action", "continue"),
                direction=result.get("direction", ""),
                suggestion=result.get("suggestion", ""),
                confidence=result.get("confidence", 0.5),
                is_final=result.get("is_final", False),
            )
        except Exception as e:
            logger.error(f"AI优化决策失败: {e}")
            # 安全降级
            if iteration > 5:
                return OptimizationDecision(
                    action="stop",
                    direction="达到最大迭代次数",
                    suggestion="已达到最大迭代次数，建议人工审查",
                    confidence=0.3,
                    is_final=False,
                )
            return OptimizationDecision(
                action="continue",
                direction="AI决策失败，尝试继续",
                suggestion="请检查模型输出",
                confidence=0.1,
                is_final=False,
            )
