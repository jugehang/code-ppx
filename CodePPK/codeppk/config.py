"""Global configuration for CodePPK.

Manages LLM provider settings, NONMEM paths, project paths, and
loads configuration from environment variables or config files.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LLMConfig:
    """LLM provider configuration.

    Supports three provider types:
    - 'local': OpenAI-compatible local server (LM Studio, Ollama)
    - 'api': Remote API (OpenAI, Anthropic, DeepSeek, Azure)
    - 'plugin': VS Code extension bridge (Claude Code, Codex)
    """
    provider: str = "local"  # local | api | plugin
    model_id: str = "google/gemma-4-26b-a4b"
    base_url: str = "http://localhost:1234/v1"
    api_key: str = "lm-studio"
    # For vision tasks (GOF/VPC image audit)
    vision_provider: Optional[str] = None  # defaults to provider
    vision_model_id: Optional[str] = None  # defaults to model_id
    vision_base_url: Optional[str] = None
    vision_api_key: Optional[str] = None
    # Plugin bridge settings
    plugin_command: str = ""  # e.g. "claude-code" or "codex"
    # Generation params
    temperature: float = 0.1
    max_tokens: int = 4000

    def resolve_vision(self) -> "LLMConfig":
        """Return a LLMConfig with vision fields filled from text fields."""
        return LLMConfig(
            provider=self.vision_provider or self.provider,
            model_id=self.vision_model_id or self.model_id,
            base_url=self.vision_base_url or self.base_url,
            api_key=self.vision_api_key or self.api_key,
            plugin_command=self.plugin_command,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


@dataclass
class ProjectConfig:
    """Project-level configuration for a modeling run."""
    project_dir: Path = Path.cwd()
    data_file: str = "NM_dat_new.csv"
    rules_file: str = "poppk_rules.json"
    prev_run: str = ""
    curr_run: str = "1"
    # NONMEM / PsN settings
    nonmem_executable: str = "nmfe76"
    psn_execute_template: str = "execute {model} -model_dir_name"
    # Rules path (relative to PopPK_Agent or absolute)
    rules_base_dir: Path = Path(__file__).resolve().parent.parent.parent / "PopPK_Agent"
    # Templates base dir
    templates_base_dir: Path = Path(__file__).resolve().parent.parent.parent / "PopPK_Agent"
    # R scripts base dir
    r_scripts_dir: Path = Path(__file__).resolve().parent.parent.parent / "PopPK_Agent"

    @property
    def project_path(self) -> Path:
        return Path(self.project_dir).resolve()

    @property
    def rules_path(self) -> Path:
        return Path(self.rules_file) if Path(self.rules_file).is_absolute() else self.rules_base_dir / self.rules_file

    @property
    def data_path(self) -> Path:
        return self.project_path / self.data_file


def load_config_from_env() -> LLMConfig:
    """Load LLM configuration from environment variables.

    Environment variables:
    - CODEPPK_LLM_PROVIDER: local | api | plugin
    - CODEPPK_LLM_MODEL: model ID
    - CODEPPK_LLM_BASE_URL: API base URL
    - CODEPPK_LLM_API_KEY: API key
    - CODEPPK_LLM_VISION_MODEL: vision model ID (optional)
    - CODEPPK_LLM_PLUGIN_CMD: plugin command for VS Code bridge
    """
    return LLMConfig(
        provider=os.environ.get("CODEPPK_LLM_PROVIDER", "local"),
        model_id=os.environ.get("CODEPPK_LLM_MODEL", "google/gemma-4-26b-a4b"),
        base_url=os.environ.get("CODEPPK_LLM_BASE_URL", "http://localhost:1234/v1"),
        api_key=os.environ.get("CODEPPK_LLM_API_KEY", "lm-studio"),
        vision_model_id=os.environ.get("CODEPPK_LLM_VISION_MODEL"),
        plugin_command=os.environ.get("CODEPPK_LLM_PLUGIN_CMD", ""),
    )
