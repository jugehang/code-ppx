"""GOF diagnostic plot AI audit.

Generates GOF plots via R scripts, then sends them to the LLM
for visual diagnostic assessment using the rule library.
"""
import shutil
from pathlib import Path
from typing import Optional

from ..llm.base import BaseLLMProvider
from ..rules.loader import RuleLibrary
from .r_scripts import run_gof_plot


def find_gof_image(project_dir: Path, run_id: str) -> Optional[Path]:
    """Find the GOF image file for a run."""
    for suffix in ("jpg", "JPG", "jpeg", "JPEG", "png", "PNG"):
        candidate = project_dir / f"GOF_mod{run_id}.{suffix}"
        if candidate.exists():
            return candidate
    return None


def audit_gof(llm: BaseLLMProvider, rules: RuleLibrary,
              project_dir: Path, run_id: str, prev_run_id: str = "",
              log=None) -> str:
    """Run GOF plot generation and AI visual audit.

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
        log(f"Generating GOF plots for run {run_id}...")

    # Generate GOF plot
    run_gof_plot(project_dir, run_id, log or print)

    # Find the image
    current_image = find_gof_image(project_dir, run_id)
    if not current_image:
        return f"**GOF audit skipped**: No GOF image found for run {run_id}."

    # Build prompt
    rules_context = rules.as_context()
    prev_text = f" and compare with Run {prev_run_id}" if prev_run_id else ""

    prompt = f"""You are a senior PopPK visual diagnostics expert. Please systematically audit the provided GOF (Goodness-of-Fit) diagnostic plot{prev_text}.

### Rule Library
{rules_context}

### Your Tasks
1. Identify the key subplots (DV vs PRED, DV vs IPRED, CWRES vs TIME, CWRES vs PRED, |IWRES| vs IPRED).
2. For each subplot, assess:
   - Is the line of identity well-aligned?
   - Are there systematic biases or trends in residuals?
   - Are |CWRES| values mostly < 6?
   - Is there heteroscedasticity in |IWRES| vs IPRED?
3. If a previous model image is provided, compare the evolution.
4. Reference specific Rule IDs from the rule library in your assessment.
5. Provide a clear verdict: Is the GOF acceptable? What are the main issues?

Please output your report in Markdown format."""

    # Find previous GOF image for comparison
    prev_image = None
    if prev_run_id:
        prev_image = find_gof_image(project_dir, prev_run_id)

    if log:
        log("Sending GOF visual audit request to LLM...")

    response = llm.chat_with_image(
        prompt=prompt,
        image_path=current_image,
        temperature=0.1,
        max_tokens=3000,
    )

    if not response.success:
        return f"**GOF audit failed**: {response.error}"

    report = f"# GOF Diagnostic AI Audit Report\n\n"
    report += f"- **Run**: {run_id}"
    if prev_run_id:
        report += f" | **Previous**: {prev_run_id}"
    report += f"\n- **Image**: `{current_image.name}`\n\n---\n\n"
    report += response.text

    # Save report
    report_path = project_dir / f"GOF_AI_Audit_Run{run_id}.md"
    report_path.write_text(report, encoding="utf-8")

    if log:
        log(f"GOF audit report saved: {report_path}")

    return report
