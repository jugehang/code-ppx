"""LLM-driven decision making for model optimization.

Given the current model's LST results, GOF/VPC audit reports, and rule
library, asks the LLM to decide the next optimization step.
"""
import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..llm.base import BaseLLMProvider
from ..nonmem.lst_parser import LSTResults
from ..rules.loader import RuleLibrary


class ActionType(str, Enum):
    """Possible actions the AI can decide to take."""
    FINALIZE = "finalize"  # Model is good enough, stop
    REPAIR_CONTROL_STREAM = "repair"  # Fix .mod syntax errors
    ADD_COVARIATE = "add_covariate"  # Add a covariate effect
    ADD_IIV = "add_iiv"  # Add inter-individual variability
    ESCALATE_STRUCTURE = "escalate"  # Move to more complex model (1->2->3 cmt)
    SIMPLIFY_STRUCTURE = "simplify"  # Move to simpler model
    CHANGE_ERROR_MODEL = "change_error"  # Modify residual error structure
    SWITCH_TO_NONLINEAR = "switch_nonlinear"  # Switch to MM or TMDD model
    RERUN = "rerun"  # Re-run with adjusted initial estimates
    RUN_VPC = "run_vpc"  # Generate VPC (if GOF looks OK)
    RUN_BOOTSTRAP = "run_bootstrap"  # Run bootstrap validation


@dataclass
class ModelDecision:
    """A decision made by the LLM about the next optimization step."""
    action: ActionType
    reasoning: str = ""
    target_parameter: str = ""  # e.g. "CL", "V1" for covariate/IIV
    covariate: str = ""  # e.g. "WT", "AGE" for add_covariate
    new_template: str = ""  # for escalate/simplify
    new_initial_estimates: dict = None  # for rerun
    confidence: float = 0.0  # 0-1, LLM's confidence in this decision
    details: str = ""  # Additional details

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "reasoning": self.reasoning,
            "target_parameter": self.target_parameter,
            "covariate": self.covariate,
            "new_template": self.new_template,
            "confidence": self.confidence,
            "details": self.details,
        }


def make_decision(llm: BaseLLMProvider, rules: RuleLibrary,
                  lst_results: LSTResults, features_summary: str,
                  gof_report: str = "", vpc_report: str = "",
                  iteration: int = 0, max_iterations: int = 10,
                  log=None) -> ModelDecision:
    """Ask the LLM to decide the next optimization step.

    Args:
        llm: LLM provider.
        rules: Rule library for context.
        lst_results: Parsed LST results from the current run.
        features_summary: Dataset feature summary.
        gof_report: GOF audit report (if available).
        vpc_report: VPC audit report (if available).
        iteration: Current iteration number.
        max_iterations: Maximum allowed iterations.
        log: Logging function.

    Returns:
        ModelDecision with the recommended next action.
    """
    rules_context = rules.as_context(max_chars=40000)

    # Build the status summary
    status_parts = [
        f"### Current Model Status (Iteration {iteration}/{max_iterations})",
        f"\n#### Dataset Features\n{features_summary}",
        f"\n#### LST Results\n{lst_results.summary()}",
    ]

    if lst_results.has_errors:
        status_parts.append(f"\n#### Error Messages\n")
        for err in lst_results.error_messages[:10]:
            status_parts.append(f"- {err[:200]}")

    if lst_results.parameters:
        status_parts.append(f"\n#### Parameter Estimates")
        for p in lst_results.parameters:
            status_parts.append(
                f"- {p.name}: {p.theta_value} (RSE: {p.theta_rse:.1f}%, "
                f"IIV CV: {p.iiv_cv:.1f}%, Eta Shrink: {p.eta_shrink:.1f}%)"
            )

    if gof_report:
        status_parts.append(f"\n#### GOF Audit Report\n{gof_report[:3000]}")

    if vpc_report:
        status_parts.append(f"\n#### VPC Audit Report\n{vpc_report[:3000]}")

    status = "\n".join(status_parts)

    prompt = f"""You are a senior PopPK modeler deciding the next optimization step for an automated modeling pipeline.

### Rule Library
{rules_context}

### {status}

### Decision Framework
Based on the current model status, decide the next action:

1. **FINALIZE**: If the model has:
   - Successful estimation with covariance step
   - OFV is reasonable and stable
   - GOF shows no major bias (CWRES mostly within ±6)
   - VPC shows good predictive performance
   - No parameter has RSE > 30% or shrinkage > 30% (unless justified)

2. **REPAIR_CONTROL_STREAM**: If there are NMTRAN errors or the estimation failed.
   - Identify the specific block to fix from error messages.

3. **ADD_COVARIATE**: If GOF shows trends related to a covariate (e.g., weight, study).
   - Specify which parameter and which covariate.

4. **ADD_IIV**: If a parameter has very low IIV or high shrinkage, consider adding/removing IIV.
   - Specify which parameter.

5. **ESCALATE_STRUCTURE**: If the structural model is misspecified (e.g., bi-exponential decay not captured by 1-cmt).
   - Specify the target template (e.g., 2-cmt or 3-cmt).

6. **SIMPLIFY_STRUCTURE**: If parameters are unidentifiable or estimation is unstable.
   - Specify the simpler template.

7. **CHANGE_ERROR_MODEL**: If |IWRES| vs IPRED shows heteroscedasticity.
   - Specify the new error model type.

8. **SWITCH_TO_NONLINEAR**: If GOF/VPC shows dose-dependent clearance or nonlinear PK.
   - Specify the target template: `iv_mm_advan10_trans1` (Michaelis-Menten) or `iv_tmdd_advan13` (full TMDD).
   - Use MM first as a simpler approximation; escalate to TMDD if MM is insufficient.

9. **RUN_VPC**: If GOF looks acceptable but VPC hasn't been run yet.

10. **RUN_BOOTSTRAP**: If GOF and VPC are acceptable, run bootstrap for final validation.

### Output Format
Respond with ONLY a JSON object (no markdown fences):
{{
  "action": "<action_type>",
  "reasoning": "<detailed explanation>",
  "target_parameter": "<parameter name if applicable>",
  "covariate": "<covariate name if applicable>",
  "new_template": "<template ID if applicable>",
  "confidence": <0.0-1.0>,
  "details": "<any additional details>"
}}
"""

    if log:
        log("Asking LLM for next optimization decision...")

    response = llm.simple_chat(prompt, temperature=0.1, max_tokens=2000)

    return _parse_decision(response)


def _parse_decision(text: str) -> ModelDecision:
    """Parse the LLM's decision response."""
    # Remove markdown fences if present
    clean = text.strip().replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        # Try to find JSON in the text
        import re
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return ModelDecision(
                    action=ActionType.RERUN,
                    reasoning=f"Could not parse LLM decision: {text[:200]}",
                    confidence=0.0,
                )
        else:
            return ModelDecision(
                action=ActionType.RERUN,
                reasoning=f"Could not parse LLM decision: {text[:200]}",
                confidence=0.0,
            )

    action_str = data.get("action", "rerun").lower()
    try:
        action = ActionType(action_str)
    except ValueError:
        # Try to match partial
        for a in ActionType:
            if a.value in action_str:
                action = a
                break
        else:
            action = ActionType.RERUN

    return ModelDecision(
        action=action,
        reasoning=data.get("reasoning", ""),
        target_parameter=data.get("target_parameter", ""),
        covariate=data.get("covariate", ""),
        new_template=data.get("new_template", ""),
        confidence=float(data.get("confidence", 0.0)),
        details=data.get("details", ""),
    )
