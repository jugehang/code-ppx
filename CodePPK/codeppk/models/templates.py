"""NONMEM model templates — re-export from PopPK_Agent.

This module re-exports the proven template definitions from
PopPK_Agent/poppk_model_templates.py, making them available as
part of the CodePPK package interface.
"""

# Re-export everything from generator.py (which handles the import bridge)
from .generator import (
    TEMPLATES,
    TemplateSpec,
    recommended_template_id,
    render_model,
    normalize_input_columns,
    HAS_TEMPLATES,
)

__all__ = [
    "TEMPLATES",
    "TemplateSpec",
    "recommended_template_id",
    "render_model",
    "normalize_input_columns",
    "HAS_TEMPLATES",
]
