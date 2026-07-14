"""
AI驱动的模型诊断与迭代优化引擎

参考 pyDarwin 的迭代搜索架构，但用AI替代穷举搜索:

pyDarwin路径:  Template + Tokens → 穷举/GA搜索 → NONMEM → fitness排序 → 最优模型
本工具路径:    数据画像 → NCA初始值 → 生成模型 → NONMEM → AI诊断(LST+GOF+VPC) → AI决策优化方向 → 迭代

迭代决策树 (AI根据诊断结果选择):
  收敛失败      → 诊断错误 → 调整初始值/简化结构 → 重新运行
  OFV高/残差偏  → 添加协变量/升级结构/修改误差模型
  CWRES有趋势   → 添加协变量/改变残差模型
  Shrinkage高  → 移除该参数IIV
  VPC不覆盖    → 调整IIV/添加协变量
  全部良好     → 定稿
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum

logger = logging.getLogger(__name__)


class ActionType(Enum):
    """迭代动作类型"""
    REPAIR = "repair"                    # 修复运行失败的模型
    ADJUST_INITIAL = "adjust_initial"     # 调整初始值
    ADD_COVARIATE = "add_covariate"       # 添加协变量
    REMOVE_COVARIATE = "remove_covariate" # 移除协变量
    ADD_IIV = "add_iiv"                   # 添加个体间变异
    REMOVE_IIV = "remove_iiv"            # 移除个体间变异
    ESCALATE_STRUCTURE = "escalate"       # 升级结构 (1室→2室, 线性→TMDD)
    SIMPLIFY_STRUCTURE = "simplify"       # 简化结构
    CHANGE_ERROR = "change_error"         # 修改残差模型
    RERUN = "rerun"                       # 用新初始值重跑
    FINALIZE = "finalize"                 # 定稿
    STOP = "stop"                         # 停止


@dataclass
class DiagnosticDecision:
    """AI诊断决策"""
    action: ActionType
    reason: str                           # 决策原因
    target_parameter: str = ""            # 目标参数 (如CL/V1)
    target_covariate: str = ""            # 目标协变量 (如WT/AGE)
    new_initial_values: dict = field(default_factory=dict)  # 新初始值
    new_error_model: str = ""             # 新误差模型
    confidence: float = 0.0               # 置信度

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "target_parameter": self.target_parameter,
            "target_covariate": self.target_covariate,
            "new_initial_values": self.new_initial_values,
            "new_error_model": self.new_error_model,
            "confidence": self.confidence,
        }


class DiagnosticEngine:
    """AI驱动的模型诊断引擎"""

    def __init__(self, llm_backend, rule_engine):
        self.llm = llm_backend
        self.rules = rule_engine

    def diagnose_and_decide(
        self,
        run_id: int,
        lst_result: dict,
        gof_report: str = "",
        vpc_report: str = "",
        prev_ofv: Optional[float] = None,
        iteration: int = 1,
        data_profile: dict = None,
    ) -> DiagnosticDecision:
        """
        综合LST解析+GOF审计+VPC审计，AI决定下一步优化方向

        Args:
            lst_result: LST解析结果
            gof_report: GOF视觉审计报告
            vpc_report: VPC视觉审计报告
            prev_ofv: 前序模型OFV
            iteration: 当前迭代次数
            data_profile: 数据画像

        Returns:
            DiagnosticDecision
        """
        # 如果NONMEM运行失败，优先修复
        if not lst_result.get("success", False):
            return self._decide_repair(lst_result, data_profile)

        ofv = lst_result.get("ofv")
        if ofv is None:
            return DiagnosticDecision(
                action=ActionType.REPAIR,
                reason="OFV无法提取，可能模型未收敛",
                confidence=0.8
            )

        # 收集诊断信号
        signals = self._collect_signals(lst_result, gof_report, vpc_report, prev_ofv, ofv)

        # AI综合决策
        return self._ai_decision(signals, iteration, data_profile)

    def _collect_signals(
        self, lst_result: dict, gof_report: str, vpc_report: str,
        prev_ofv: Optional[float], ofv: float
    ) -> dict:
        """收集所有诊断信号"""
        signals = {
            "ofv": ofv,
            "delta_ofv": (ofv - prev_ofv) if prev_ofv else None,
            "warnings": lst_result.get("warnings", []),
            "errors": lst_result.get("errors", []),
            "gof_report": gof_report[:2000] if gof_report else "",
            "vpc_report": vpc_report[:2000] if vpc_report else "",
        }

        # 从GOF报告中提取关键信号
        gof_text = gof_report.lower() if gof_report else ""
        signals["gof_bias"] = "偏倚" in gof_text or "bias" in gof_text or "偏离" in gof_text
        signals["gof_trend"] = "趋势" in gof_text or "trend" in gof_text
        signals["gof_good"] = "良好" in gof_text or "good" in gof_text or "acceptable" in gof_text
        signals["gof_cwres_high"] = "cwres" in gof_text and ("6" in gof_text or "outlier" in gof_text)

        # 从VPC报告中提取
        vpc_text = vpc_report.lower() if vpc_report else ""
        signals["vpc_misfit"] = "不覆盖" in vpc_text or "misfit" in vpc_text or "偏离" in vpc_text
        signals["vpc_good"] = "覆盖" in vpc_text and "良好" in vpc_text

        return signals

    def _ai_decision(self, signals: dict, iteration: int, data_profile: dict) -> DiagnosticDecision:
        """AI综合所有信号做决策"""
        import json

        # 构建决策prompt
        eval_rules = self.rules.format_for_prompt(namespaces=["@ModelEvaluation", "@CovariateAnalysis"]) if self.rules else ""

        available_covs = []
        if data_profile:
            available_covs = data_profile.get("continuous_covariates", []) + data_profile.get("categorical_covariates", [])

        prompt = f"""你是群体药动学(PopPK)建模专家。请基于以下诊断信号，决定下一步优化方向。

### 当前迭代: #{iteration}

### 诊断信号
- OFV: {signals.get('ofv')}
- ΔOFV (vs前序): {signals.get('delta_ofv')}
- GOF有偏倚: {signals.get('gof_bias')}
- GOF有趋势: {signals.get('gof_trend')}
- GOF良好: {signals.get('gof_good')}
- CWRES过高: {signals.get('gof_cwres_high')}
- VPC不覆盖: {signals.get('vpc_misfit')}
- VPC良好: {signals.get('vpc_good')}
- 警告: {signals.get('warnings', [])[:3]}

### GOF审计报告摘要
{signals.get('gof_report', 'N/A')[:1000]}

### VPC审计报告摘要
{signals.get('vpc_report', 'N/A')[:1000]}

### 可用协变量
{available_covs}

### 评估规则参考
{eval_rules[:2000]}

### 决策选项
1. "finalize" - 模型已达标(GOF良好+VPC良好+无严重警告), 可定稿
2. "add_covariate" - GOF有偏倚或趋势, 需要添加协变量 (指定参数和协变量)
3. "change_error" - 残差有趋势, 需要改变误差模型 (proportional/additive/combined)
4. "escalate" - 当前结构不足, 需要升级 (如1室→2室, 线性→TMDD)
5. "simplify" - 模型过度参数化, 需要简化
6. "adjust_initial" - 收敛有问题, 需要调整初始值
7. "rerun" - 仅用新初始值重跑当前模型
8. "stop" - 无法进一步改进

### 输出格式 (严格JSON)
{{
  "action": "finalize/add_covariate/change_error/escalate/simplify/adjust_initial/rerun/stop",
  "reason": "决策原因(一句话)",
  "target_parameter": "CL或V1或Q或V2 (如适用)",
  "target_covariate": "WT或AGE或SEX等 (如适用)",
  "new_error_model": "proportional/additive/combined (如适用)",
  "new_initial_values": {{"CL": 0.012, "V1": 4.0}},
  "confidence": 0.8
}}
"""
        try:
            result = self.llm.chat_json(prompt)
            action_str = result.get("action", "rerun")
            try:
                action = ActionType(action_str)
            except ValueError:
                action = ActionType.RERUN

            return DiagnosticDecision(
                action=action,
                reason=result.get("reason", ""),
                target_parameter=result.get("target_parameter", ""),
                target_covariate=result.get("target_covariate", ""),
                new_initial_values=result.get("new_initial_values", {}),
                new_error_model=result.get("new_error_model", ""),
                confidence=result.get("confidence", 0.5),
            )
        except Exception as e:
            logger.error(f"AI决策失败: {e}")
            # 安全降级
            if iteration > 10:
                return DiagnosticDecision(ActionType.STOP, "达到最大迭代", confidence=0.3)
            return DiagnosticDecision(ActionType.RERUN, "AI决策失败, 尝试重跑", confidence=0.1)

    def _decide_repair(self, lst_result: dict, data_profile: dict) -> DiagnosticDecision:
        """运行失败时的修复决策"""
        errors = lst_result.get("errors", [])
        error_text = " ".join(errors).lower()

        if "parameter estimate is near its boundary" in error_text:
            return DiagnosticDecision(
                action=ActionType.ADJUST_INITIAL,
                reason="参数接近边界，需要调整初始值",
                confidence=0.9
            )
        elif "minimization terminated" in error_text:
            return DiagnosticDecision(
                action=ActionType.ADJUST_INITIAL,
                reason="最小化终止，需要调整初始值或简化模型",
                confidence=0.8
            )
        elif "covariance step aborted" in error_text:
            return DiagnosticDecision(
                action=ActionType.RERUN,
                reason="协方差步骤失败，重试",
                confidence=0.7
            )
        elif "rounding errors" in error_text:
            return DiagnosticDecision(
                action=ActionType.ADJUST_INITIAL,
                reason="舍入误差，调整初始值",
                confidence=0.6
            )
        else:
            return DiagnosticDecision(
                action=ActionType.REPAIR,
                reason=f"运行失败: {errors[:2]}",
                confidence=0.5
            )


def apply_decision(
    mod_content: str,
    decision: DiagnosticDecision,
    nca_params: dict = None,
) -> str:
    """
    将AI决策应用到模型控制流

    根据 ActionType 执行确定性修改:
    """
    from model_generator import (
        apply_modifications, Modification,
        _add_covariate, _add_iiv, _fix_residual_error,
        _bump_run, parse_sections, rebuild_mod
    )

    if decision.action == ActionType.FINALIZE or decision.action == ActionType.STOP:
        return mod_content  # 不修改

    if decision.action == ActionType.ADJUST_INITIAL or decision.action == ActionType.RERUN:
        # 调整初始值
        if decision.new_initial_values:
            mod_content = _adjust_theta_values(mod_content, decision.new_initial_values)
        return mod_content

    if decision.action == ActionType.ADD_COVARIATE:
        if decision.target_parameter and decision.target_covariate:
            return _add_covariate(mod_content, decision.target_parameter, decision.target_covariate)
        return mod_content

    if decision.action == ActionType.ADD_IIV:
        if decision.target_parameter:
            return _add_iiv(mod_content, decision.target_parameter)
        return mod_content

    if decision.action == ActionType.CHANGE_ERROR:
        if decision.new_error_model:
            return _fix_residual_error(mod_content, decision.new_error_model)
        return mod_content

    if decision.action == ActionType.ESCALATE_STRUCTURE:
        # 从1室升级到2室 或 从线性升级到TMDD
        from poppk_model_templates import render_model
        # 提取run_id
        import re
        m = re.search(r'run(\d+)', mod_content[:500])
        run_id = m.group(1) if m else "1"
        return render_model("iv_infusion_2c_advan3_trans4", run_id)

    if decision.action == ActionType.SIMPLIFY_STRUCTURE:
        from poppk_model_templates import render_model
        import re
        m = re.search(r'run(\d+)', mod_content[:500])
        run_id = m.group(1) if m else "1"
        return render_model("iv_infusion_1c_advan1_trans2", run_id)

    if decision.action == ActionType.REPAIR:
        return mod_content  # AI修复会在下一轮诊断中处理

    return mod_content


def _adjust_theta_values(mod_content: str, new_values: dict) -> str:
    """调整THETA初始值

    new_values: {"CL": 0.015, "V1": 4.5}
    """
    # 参数名到注释的映射 (用于在$THETA块中定位)
    param_comments = {
        "CL": ["CL_L/h", "CL", "Clearance"],
        "V1": ["V1_L", "V1", "Volume"],
        "V": ["V_L", "V", "Volume"],
        "Q": ["Q_L/h", "Q", "Inter"],
        "V2": ["V2_L", "V2"],
        "VM": ["VM", "Vmax"],
        "KM": ["KM", "Km"],
    }

    sections = parse_sections(mod_content)
    theta_block = sections.get("$THETA", "")
    lines = theta_block.split('\n')

    new_lines = [lines[0]]  # $THETA 行

    for line in lines[1:]:
        modified = False
        for param, value in new_values.items():
            comments = param_comments.get(param, [param])
            if any(c.lower() in line.lower() for c in comments):
                # 替换初始值 (括号内第二个值)
                import re
                match = re.match(r'(\([\d\.\-]+,\s*)([\d\.\-]+)(.*)', line)
                if match:
                    line = f"{match.group(1)}{value}{match.group(3)}"
                    modified = True
                    break
        new_lines.append(line)

    sections["$THETA"] = '\n'.join(new_lines)
    return rebuild_mod(sections)
