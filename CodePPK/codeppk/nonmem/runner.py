"""NONMEM execution via PsN or direct nmfe.

Wraps the proven execution logic from PopPK_Agent/workbench_core.py,
providing a clean interface for the automation engine.
"""
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

LogFn = Callable[[str], None]


@dataclass
class RunResult:
    """Result of a NONMEM execution."""
    return_code: int
    lst_path: Optional[Path] = None
    output_dir: Optional[Path] = None
    success: bool = False
    error: str = ""


def mac_nonmem_env() -> Dict[str, str]:
    """Get macOS environment for NONMEM execution."""
    sdk_path = "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"
    env = os.environ.copy()
    if Path(sdk_path).exists():
        env["SDKROOT"] = sdk_path
        env["LIBRARY_PATH"] = f"{sdk_path}/usr/lib"
        env["CPATH"] = f"{sdk_path}/usr/include"
    return env


def find_nonmem_executable() -> str:
    """Find the NONMEM executable."""
    for name in ("nmfe76", "nmfe75", "nmfe74", "nmfe73", "nmfe72", "nmfe71", "nmfe70", "nonmem"):
        found = shutil.which(name)
        if found:
            return found
    return "nmfe76"


def find_psn_tool(tool: str) -> str:
    """Find a PsN tool (execute, vpc, bootstrap, scm)."""
    found = shutil.which(tool)
    if found:
        return found
    return f"/usr/local/bin/{tool}"


def stream_subprocess(command: List[str], cwd: Path, log: LogFn,
                       env: Optional[Dict[str, str]] = None) -> int:
    """Run a subprocess and stream output to the log function."""
    cmd_list = list(command)
    log(f"$ {' '.join(shlex.quote(part) for part in cmd_list)}")
    process = subprocess.Popen(
        cmd_list,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        log(line.rstrip())
    return_code = process.wait()
    log(f"[exit {return_code}]")
    return return_code


def run_nonmem(project_dir: Path, run_id: str, log: LogFn,
               use_psn: bool = True, directory: Optional[str] = None) -> RunResult:
    """Run NONMEM on a model file.

    Args:
        project_dir: Project directory containing the .mod file.
        run_id: Run number (e.g. '42').
        log: Logging function.
        use_psn: If True, use PsN execute; if False, use nmfe directly.
        directory: Output directory name (PsN only).

    Returns:
        RunResult with execution outcome.
    """
    model_name = f"run{run_id}.mod"
    mod_path = project_dir / model_name

    if not mod_path.exists():
        return RunResult(
            return_code=1,
            success=False,
            error=f"Model file not found: {mod_path}",
        )

    if use_psn:
        execute_cmd = find_psn_tool("execute")
        if directory:
            command = [execute_cmd, model_name, f"-directory={directory}"]
        else:
            command = [execute_cmd, model_name, "-model_dir_name"]
    else:
        nmfe = find_nonmem_executable()
        command = [nmfe, model_name, f"run{run_id}.lst"]

    code = stream_subprocess(command, project_dir, log, env=mac_nonmem_env())

    lst_path = project_dir / f"run{run_id}.lst"
    output_dir = project_dir / (directory or f"nonmem_run_{run_id}")

    return RunResult(
        return_code=code,
        lst_path=lst_path if lst_path.exists() else None,
        output_dir=output_dir if output_dir.exists() else None,
        success=(code == 0 and lst_path.exists()),
        error="" if code == 0 else f"NONMEM exited with code {code}",
    )


def run_psn_vpc(project_dir: Path, run_id: str, log: LogFn,
                samples: int = 500, stratify_var: str = "STUDY") -> RunResult:
    """Run PsN VPC.

    Args:
        project_dir: Project directory.
        run_id: Run number.
        log: Logging function.
        samples: Number of VPC samples.
        stratify_var: Variable to stratify on.

    Returns:
        RunResult with execution outcome.
    """
    vpc_cmd = find_psn_tool("vpc")
    command = [
        vpc_cmd,
        f"run{run_id}.mod",
        f"-samples={samples}",
        f"-dir=vpc_dir_{run_id}",
        f"-stratify_on={stratify_var}",
        "-idv=TIME",
        "-bin_by_count=1",
        "-no_of_bins=12",
    ]
    code = stream_subprocess(command, project_dir, log, env=mac_nonmem_env())
    return RunResult(
        return_code=code,
        success=(code == 0),
        output_dir=project_dir / f"vpc_dir_{run_id}",
    )


def run_psn_bootstrap(project_dir: Path, run_id: str, log: LogFn,
                      samples: int = 200) -> RunResult:
    """Run PsN bootstrap.

    Args:
        project_dir: Project directory.
        run_id: Run number.
        log: Logging function.
        samples: Number of bootstrap samples.

    Returns:
        RunResult with execution outcome.
    """
    bootstrap_cmd = find_psn_tool("bootstrap")
    command = [
        bootstrap_cmd,
        f"run{run_id}.mod",
        f"-samples={samples}",
        f"-dir=bootstrap_dir_{run_id}",
    ]
    code = stream_subprocess(command, project_dir, log, env=mac_nonmem_env())
    return RunResult(
        return_code=code,
        success=(code == 0),
        output_dir=project_dir / f"bootstrap_dir_{run_id}",
    )
