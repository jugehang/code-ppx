"""Model generation, templates, and validation.

This module re-exports the proven deterministic model generator and
templates from PopPK_Agent, with fallback stubs if not available.
"""
import sys
from pathlib import Path
from typing import List, Optional

# Add PopPK_Agent to path for importing proven modules
_PopPK_AGENT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "PopPK_Agent"
if str(_PopPK_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PopPK_AGENT_DIR))

# Try to import from PopPK_Agent
try:
    from poppk_model_templates import (
        TEMPLATES,
        TemplateSpec,
        recommended_template_id,
        render_model,
        normalize_input_columns,
    )
    HAS_TEMPLATES = True
except ImportError:
    HAS_TEMPLATES = False
    TEMPLATES = {}
    TemplateSpec = None
    recommended_template_id = None
    normalize_input_columns = None
    render_model = None

try:
    from model_generator import (
        apply_modifications,
        apply_structured,
        generate_from_template,
        Modification,
        parse_sections,
        rebuild_mod,
        ACTION_REGISTRY,
    )
    HAS_GENERATOR = True
except ImportError:
    HAS_GENERATOR = False
    apply_modifications = None
    apply_structured = None
    generate_from_template = None
    Modification = None
    parse_sections = None
    rebuild_mod = None
    ACTION_REGISTRY = {}

try:
    from mod_validator import validate_mod, ValidationResult, ValidationIssue
    HAS_VALIDATOR = True
except ImportError:
    HAS_VALIDATOR = False
    validate_mod = None
    ValidationResult = None
    ValidationIssue = None


def generate_initial_model(template_id: str, run_id: str,
                           data_file: str = "NM_dat_new.csv",
                           input_columns: Optional[List[str]] = None) -> str:
    """Generate an initial .mod file from a template.

    Args:
        template_id: Template ID (e.g. 'iv_infusion_1c_advan1_trans2').
        run_id: Run number string.
        data_file: Data file name.
        input_columns: Optional list of input column names.

    Returns:
        The generated .mod file content as a string.
    """
    if not HAS_TEMPLATES or render_model is None:
        raise RuntimeError(
            "Model templates not available. Ensure PopPK_Agent is in the path."
        )

    if input_columns and normalize_input_columns:
        input_columns = normalize_input_columns(input_columns)

    return render_model(
        template_id=template_id,
        run_id=run_id,
        data_file=data_file,
        input_columns=input_columns,
    )


def validate_and_autofix(mod_path: Path, project_dir: Path,
                         csv_path: Optional[Path] = None,
                         run_id: str = "") -> dict:
    """Validate a .mod file and auto-fix common issues.

    Args:
        mod_path: Path to the .mod file.
        project_dir: Project directory.
        csv_path: Optional CSV dataset path.
        run_id: Run ID.

    Returns:
        Dictionary with validation results and fix status.
    """
    if not HAS_VALIDATOR or validate_mod is None:
        return {"passed": True, "issues": [], "auto_fixed": False, "message": "Validator not available"}

    result = validate_mod(
        mod_path,
        project_dir=project_dir,
        csv_path=csv_path if csv_path and csv_path.exists() else None,
        run_id=run_id,
    )

    if result.passed:
        return {
            "passed": True,
            "issues": [str(i) for i in result.issues],
            "auto_fixed": False,
            "message": "Validation passed",
        }

    # Try auto-fix
    if HAS_GENERATOR and apply_modifications:
        from ..nonmem.runner import mac_nonmem_env
        import re

        text = mod_path.read_text(encoding="utf-8")
        modifications = []

        # Fix $INPUT if CSV available
        if csv_path and csv_path.exists():
            header = csv_path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
            columns = [c.strip().strip('"').upper() for c in header.split(",") if c.strip()]
            modifications.append(Modification(action="fix_input", params={"columns": columns}))

        # Fix $DATA path
        modifications.append(Modification(
            action="fix_data",
            params={"data_file": csv_path.name if csv_path else "NM_dat_new.csv"},
        ))

        # Fix $TABLE file IDs
        m = re.match(r"run(\d+)", mod_path.stem, re.IGNORECASE)
        actual_run_id = m.group(1) if m else run_id
        modifications.append(Modification(
            action="fix_table_ids",
            params={"run_id": actual_run_id},
        ))

        # Fix THETA boundaries
        modifications.append(Modification(action="fix_theta_boundaries", params={}))

        try:
            fixed_text = apply_modifications(text, modifications)
            mod_path.write_text(fixed_text, encoding="utf-8")

            # Re-validate
            result2 = validate_mod(
                mod_path,
                project_dir=project_dir,
                csv_path=csv_path if csv_path and csv_path.exists() else None,
                run_id=run_id,
            )
            return {
                "passed": result2.passed,
                "issues": [str(i) for i in result2.issues],
                "auto_fixed": True,
                "message": "Auto-fix applied" + ("" if result2.passed else ", some issues remain"),
            }
        except Exception as exc:
            return {
                "passed": False,
                "issues": [str(i) for i in result.issues],
                "auto_fixed": False,
                "message": f"Auto-fix failed: {exc}",
            }

    return {
        "passed": False,
        "issues": [str(i) for i in result.issues],
        "auto_fixed": False,
        "message": "Auto-fix not available",
    }
