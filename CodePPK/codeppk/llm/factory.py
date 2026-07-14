"""LLM provider factory.

Creates the appropriate provider based on configuration, with auto-detection
for common setups (local LM Studio, API keys in env, VS Code plugins).
"""
import os
from typing import Optional

from ..config import LLMConfig
from .base import BaseLLMProvider


def create_provider(config: Optional[LLMConfig] = None) -> BaseLLMProvider:
    """Create an LLM provider based on configuration.

    Auto-detection logic:
    1. If CODEPPK_LLM_PROVIDER is set, use that.
    2. If OPENAI_API_KEY is set and no local server detected, use 'api'.
    3. If ANTHROPIC_API_KEY is set, use 'api' with Anthropic.
    4. If a VS Code plugin CLI is found (claude, codex), use 'plugin'.
    5. Default to 'local' (LM Studio at localhost:1234).

    Args:
        config: LLMConfig. If None, loads from environment.

    Returns:
        Configured BaseLLMProvider instance.
    """
    if config is None:
        from ..config import load_config_from_env
        config = load_config_from_env()

    provider_type = config.provider.lower()

    if provider_type == "api":
        from .api import APILLMProvider
        return APILLMProvider(config)

    if provider_type == "plugin":
        from .plugin import PluginLLMProvider
        return PluginLLMProvider(config)

    # Default: local
    from .local import LocalLLMProvider
    return LocalLLMProvider(config)


def auto_detect_provider() -> str:
    """Auto-detect the best available provider.

    Returns one of: 'local', 'api', 'plugin'
    """
    # Check for explicit env override
    explicit = os.environ.get("CODEPPK_LLM_PROVIDER")
    if explicit:
        return explicit.lower()

    # Check for API keys
    if os.environ.get("OPENAI_API_KEY"):
        return "api"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"

    # Check for VS Code plugin CLIs
    import shutil
    for name in ("claude", "claude-code", "codex"):
        if shutil.which(name):
            return "plugin"

    # Default to local
    return "local"
