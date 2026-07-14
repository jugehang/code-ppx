"""VS Code plugin LLM provider.

Bridges to VS Code AI extensions (Claude Code, Codex, etc.) via their
CLI interfaces. This allows using Claude Code or GitHub Copilot/Codex
as the LLM backend for automated modeling.

Supported plugins:
- 'claude-code': Anthropic's Claude Code CLI (claude-code command)
- 'codex': OpenAI Codex CLI
- 'continue': Continue.dev CLI
- 'aider': Aider AI coding assistant

The plugin is invoked as a subprocess, receiving the prompt via stdin
and returning the response via stdout. Image inputs are handled by
passing the file path reference in the prompt text.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from .base import BaseLLMProvider, LLMResponse, Message


class PluginLLMProvider(BaseLLMProvider):
    """Provider that bridges to VS Code AI plugin CLIs.

    This enables using Claude Code, Codex, or other VS Code AI extensions
    as the LLM backend. The plugin is invoked as a subprocess.

    Configuration:
    - plugin_command: The CLI command to invoke (e.g. 'claude-code')
    - model_id: Model identifier passed to the plugin (if supported)
    - base_url: Optional API URL override for the plugin

    The provider writes the prompt to a temporary file and passes it
    to the plugin, capturing stdout as the response.
    """

    def __init__(self, config):
        super().__init__(config)
        self._command = config.plugin_command or self._detect_plugin()
        if not self._command:
            raise ValueError(
                "No VS Code plugin found. Set CODEPPK_LLM_PLUGIN_CMD or "
                "install claude-code / codex CLI."
            )

    @staticmethod
    def _detect_plugin() -> str:
        """Auto-detect available VS Code AI plugin CLIs."""
        for name in ("claude", "claude-code", "codex", "aider", "continue"):
            if shutil.which(name):
                return name
        return ""

    def chat(self, messages: List[Message], temperature: float = 0.1,
             max_tokens: int = 4000) -> LLMResponse:
        try:
            # Combine messages into a single prompt
            parts = []
            for m in messages:
                prefix = f"[{m.role}]" if m.role != "user" else ""
                content = m.content if isinstance(m.content, str) else json.dumps(m.content)
                parts.append(f"{prefix} {content}".strip())
            prompt = "\n\n".join(parts)

            return self._invoke_plugin(prompt)
        except Exception as exc:
            return LLMResponse(text="", success=False, error=str(exc))

    def chat_with_image(self, prompt: str, image_path: Path,
                        temperature: float = 0.1,
                        max_tokens: int = 3000) -> LLMResponse:
        try:
            full_prompt = (
                f"{prompt}\n\n"
                f"[Image file: {image_path}]\n"
                f"Please analyze the image at the path above."
            )
            return self._invoke_plugin(full_prompt)
        except Exception as exc:
            return LLMResponse(text="", success=False, error=str(exc))

    def _invoke_plugin(self, prompt: str) -> LLMResponse:
        """Invoke the VS Code plugin CLI with the given prompt.

        Strategy:
        1. Write prompt to a temp file (avoids shell escaping issues)
        2. Invoke plugin with the temp file
        3. Capture stdout as the response
        4. Clean up temp file
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(prompt)
            temp_path = f.name

        try:
            cmd = self._build_command(temp_path)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                return LLMResponse(
                    text="",
                    success=False,
                    error=f"Plugin exited {result.returncode}: {result.stderr[:500]}",
                )
            return LLMResponse(
                text=result.stdout.strip(),
                success=True,
            )
        except subprocess.TimeoutExpired:
            return LLMResponse(
                text="",
                success=False,
                error="Plugin call timed out (300s)",
            )
        except FileNotFoundError:
            return LLMResponse(
                text="",
                success=False,
                error=f"Plugin not found: {self._command}",
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def _build_command(self, prompt_file: str) -> List[str]:
        """Build the CLI command for the detected plugin."""
        if self._command in ("claude", "claude-code"):
            cmd = [self._command, "--print", f"@{prompt_file}"]
            if self.config.model_id and self.config.model_id != "default":
                cmd.extend(["--model", self.config.model_id])
            return cmd

        if self._command == "codex":
            return [self._command, "--quiet", "--file", prompt_file]

        if self._command == "aider":
            return [self._command, "--message-file", prompt_file, "--no-auto-commits"]

        if self._command == "continue":
            return [self._command, "--prompt-file", prompt_file]

        # Generic fallback: pass file as argument
        return [self._command, prompt_file]
