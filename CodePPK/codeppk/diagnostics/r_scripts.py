"""R script dispatcher for diagnostic plots.

Runs the existing R scripts from PopPK_Agent:
- gof_plot_script.R — Goodness-of-fit plots
- individual_plot_script.R — Individual DV-time plots
- vpc_plot_script.R — VPC plots
- pk parameters script.R — PK parameter extraction
"""
import shutil
import subprocess
from pathlib import Path
from typing import List

from ..nonmem.runner import stream_subprocess, mac_nonmem_env, LogFn


def find_r_scripts_dir() -> Path:
    """Find the directory containing R scripts."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        candidate = parent / "PopPK_Agent" / "gof_plot_script.R"
        if candidate.exists():
            return candidate.parent
    return Path.cwd()


def run_r_script(script_name: str, project_dir: Path, run_id: str,
                 log: LogFn, r_scripts_dir: Path = None) -> int:
    """Run an R script with a run ID argument.

    Args:
        script_name: Name of the R script file.
        project_dir: Working directory (project root).
        run_id: Run number passed as argument.
        log: Logging function.
        r_scripts_dir: Directory containing R scripts.

    Returns:
        Exit code from Rscript.
    """
    if r_scripts_dir is None:
        r_scripts_dir = find_r_scripts_dir()

    script_path = r_scripts_dir / script_name
    if not script_path.exists():
        # Try project_dir
        script_path = project_dir / script_name
        if not script_path.exists():
            log(f"R script not found: {script_name}")
            return 2

    if not shutil.which("Rscript"):
        log("Rscript not found in PATH")
        return 127

    return stream_subprocess(
        ["Rscript", str(script_path), run_id],
        project_dir,
        log,
        env=mac_nonmem_env(),
    )


def run_gof_plot(project_dir: Path, run_id: str, log: LogFn,
                 r_scripts_dir: Path = None) -> int:
    """Generate GOF diagnostic plots."""
    return run_r_script("gof_plot_script.R", project_dir, run_id, log, r_scripts_dir)


def run_individual_plot(project_dir: Path, run_id: str, log: LogFn,
                        r_scripts_dir: Path = None) -> int:
    """Generate individual DV-time plots."""
    return run_r_script("individual_plot_script.R", project_dir, run_id, log, r_scripts_dir)


def run_vpc_plot(project_dir: Path, run_id: str, log: LogFn,
                 r_scripts_dir: Path = None) -> int:
    """Generate VPC plots."""
    return run_r_script("vpc_plot_script.R", project_dir, run_id, log, r_scripts_dir)


def run_all_diagnostics(project_dir: Path, run_id: str, log: LogFn,
                        r_scripts_dir: Path = None) -> int:
    """Run all diagnostic R scripts for a run.

    Returns the highest exit code (0 = all success).
    """
    final_code = 0
    for runner in (run_gof_plot, run_individual_plot, run_vpc_plot):
        code = runner(project_dir, run_id, log, r_scripts_dir)
        final_code = max(final_code, code)
    return final_code


def run_pk_parameters(project_dir: Path, run_id: str, log: LogFn,
                      r_scripts_dir: Path = None) -> int:
    """Run PK parameter extraction."""
    return run_r_script("pk parameters script.R", project_dir, run_id, log, r_scripts_dir)
