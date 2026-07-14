"""VPC diagnostic plot AI audit.

Generates VPC plots via R scripts, then sends them to the LLM
for visual predictive check assessment using the rule library.
"""
from pathlib import Path
from typing import Optional

from ..llm.base import BaseLLMProvider
from ..rules.loader import RuleLibrary
from .r_scripts import run_vpc_plot


def find_vpc_image(project_dir: Path, run_id: str) -> Optional[Path]:
    """Find the VPC image file for a run."""
    prefixes = [
        f"VPC_mod{run_id}",
        f"VPC_Stratified_mod{run_id}",
    ]
    for prefix in prefixes:
        for suffix in ("jpg", "JPG", "jpeg", "JPEG", "png", "PNG"):
            candidate = project_dir / f"{prefix}.{suffix}"
            if candidate.exists():
                return candidate
    return None


def audit_vpc(llm: BaseLLMProvider, rules: RuleLibrary,
              project_dir: Path, run_id: str, prev_run_id: str = "",
              log=None) -> str:
    """Run VPC plot generation and AI visual audit.

    Args:
        llm: LLM provider for vision audit.
        rules: Rule library for context.
        project_dir: Project directory.
        run_id: Current run ID.
        prev_run_id: Previous run ID (for comparison, optional).
        log: Logging function.

    Returns:
        Markdown audit report text.
    """
    if log:
        log(f"Generating VPC plots for run {run_id}...")

    # Generate VPC plot
    run_vpc_plot(project_dir, run_id, log or print)

    # Find the image
    current_image = find_vpc_image(project_dir, run_id)
    if not current_image:
        return f"**VPC audit skipped**: No VPC image found for run {run_id}."

    # Build prompt
    rules_context = rules.as_context()
    prev_text = f" and compare with Run {prev_run_id}" if prev_run_id else ""

    prompt = f"""You are a senior PopPK visual predictive check (VPC) expert. Please systematically audit the provided VPC plot{prev_text}.

### Rule Library
{rules_context}

### Your Tasks
1. Identify the VPC plot type (standard, stratified, or both).
2. Assess the following:
   - Does the observed median fall within the predicted 50th percentile interval?
   - Do the observed 5th and 95th percentiles fall within the prediction intervals?
   - Are there systematic deviations in any time region?
   - Is the binning strategy appropriate?
   - Are the prediction intervals adequately wide/narrow?
3. If a previous model VPC is provided, compare the predictive performance evolution.
4. Reference specific Rule IDs (ME-VALID-002) from the rule library.
5. Provide a clear verdict: Is the VPC acceptable? What areas need improvement?

Please output your report in Markdown format."""

    # Find previous VPC image for comparison
    prev_image = None
    if prev_run_id:
        prev_image = find_vpc_image(project_dir, prev_run_id)

    if log:
        log("Sending VPC visual audit request to LLM...")

    # If we have both current and previous, send both
    if prev_image:
        # Use the current image as primary
        response = llm.chat_with_image(
            prompt=prompt + f"\n\n[Additional reference image: previous model Run {prev_run_id}]",
            image_path=current_image,
            temperature=0.1,
            max_tokens=3000,
        )
    else:
        response = llm.chat_with_image(
            prompt=prompt,
            image_path=current_image,
            temperature=0.1,
            max_tokens=3000,
        )

    if not response.success:
        return f"**VPC audit failed**: {response.error}"

    report = f"# VPC Predictive Performance AI Audit Report\n\n"
    report += f"- **Run**: {run_id}"
    if prev_run_id:
        report += f" | **Previous**: {prev_run_id}"
    report += f"\n- **Image**: `{current_image.name}`\n\n---\n\n"
    report += response.text

    # Save report
    report_path = project_dir / f"VPC_AI_Audit_Run{run_id}.md"
    report_path.write_text(report, encoding="utf-8")

    if log:
        log(f"VPC audit report saved: {report_path}")

    return report
