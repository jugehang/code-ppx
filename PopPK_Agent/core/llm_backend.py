"""
LLM后端抽象层

支持多种LLM后端:
- lmstudio: 本地LM Studio (OpenAI兼容API)
- ollama: 本地Ollama (OpenAI兼容API)
- openai: OpenAI API
- claude: Anthropic Claude API
- codex: VS Code Codex插件
- claude_code: VS Code Claude Code插件

统一接口: chat() 文本对话, vision() 视觉多模态
"""

import base64
import logging
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

logger = logging.getLogger(__name__)


class LLMBackend:
    """LLM后端基类"""

    def __init__(self, config):
        self.config = config

    def chat(self, prompt: str, system: str = "", temperature: Optional[float] = None) -> str:
        """文本对话"""
        raise NotImplementedError

    def chat_json(self, prompt: str, system: str = "", temperature: Optional[float] = None) -> dict:
        """文本对话，返回JSON"""
        import json
        response = self.chat(prompt, system, temperature)
        # 清理可能的markdown代码块标记
        clean = response.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
        return json.loads(clean)

    def vision(self, prompt: str, image_paths: List[str], system: str = "") -> str:
        """视觉多模态对话"""
        raise NotImplementedError

    def _encode_image(self, image_path: str) -> str:
        """编码图片为Base64"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')


class OpenAICompatibleBackend(LLMBackend):
    """OpenAI兼容API后端 (LM Studio, Ollama, OpenAI等)"""

    def __init__(self, config):
        super().__init__(config)
        from openai import OpenAI
        self.client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key
        )

    def chat(self, prompt: str, system: str = "", temperature: Optional[float] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.config.model_id,
            messages=messages,
            temperature=temperature or self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return response.choices[0].message.content

    def vision(self, prompt: str, image_paths: List[str], system: str = "") -> str:
        content = [{"type": "text", "text": prompt}]
        for img_path in image_paths:
            ext = Path(img_path).suffix.lower()
            mime = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
            b64 = self._encode_image(img_path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"}
            })

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        model = self.config.vision_model_id or self.config.model_id
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=self.config.max_tokens,
        )
        return response.choices[0].message.content


class ClaudeBackend(LLMBackend):
    """Anthropic Claude API后端"""

    def __init__(self, config):
        super().__init__(config)
        import anthropic
        self.client = anthropic.Anthropic(api_key=config.api_key)

    def chat(self, prompt: str, system: str = "", temperature: Optional[float] = None) -> str:
        response = self.client.messages.create(
            model=self.config.model_id,
            max_tokens=self.config.max_tokens,
            temperature=temperature or self.config.temperature,
            system=system if system else "You are a helpful assistant.",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    def vision(self, prompt: str, image_paths: List[str], system: str = "") -> str:
        content = []
        for img_path in image_paths:
            ext = Path(img_path).suffix.lower()
            media_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
            with open(img_path, "rb") as f:
                img_data = base64.standard_b64encode(f.read()).decode("utf-8")
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": img_data}
            })
        content.append({"type": "text", "text": prompt})

        response = self.client.messages.create(
            model=self.config.model_id,
            max_tokens=self.config.max_tokens,
            system=system if system else "You are a helpful assistant.",
            messages=[{"role": "user", "content": content}]
        )
        return response.content[0].text


class VSCodePluginBackend(LLMBackend):
    """
    VS Code插件后端 (Claude Code / Codex)

    通过VS Code的命令行接口或API桥接调用。
    支持作为VS Code扩展运行时的内置LLM。
    """

    def __init__(self, config):
        super().__init__(config)
        self.plugin_type = config.backend  # claude_code | codex

    def chat(self, prompt: str, system: str = "", temperature: Optional[float] = None) -> str:
        """通过VS Code插件接口调用"""
        # 方式1: 通过CodeBuddy/扩展API桥接
        # 方式2: 通过命令行调用code --execute 或类似接口
        # 这里提供框架，实际实现取决于VS Code扩展API
        try:
            # 尝试通过扩展API调用（当作为VS Code扩展运行时）
            return self._call_via_extension_api(prompt, system)
        except Exception:
            # 降级为命令行调用
            return self._call_via_cli(prompt, system)

    def vision(self, prompt: str, image_paths: List[str], system: str = "") -> str:
        """VS Code插件的视觉接口"""
        # Claude Code支持多模态，Codex可能需要特殊处理
        return self._call_via_extension_api(prompt, system, image_paths)

    def _call_via_extension_api(self, prompt: str, system: str, image_paths: List[str] = None) -> str:
        """
        通过VS Code扩展API调用LLM

        当PopPK Agent作为VS Code扩展运行时，
        可直接访问VS Code的Language Model API。
        """
        # TODO: 实现VS Code扩展API桥接
        # 这部分将在IDE集成阶段实现
        raise NotImplementedError("VS Code扩展API桥接尚未实现，请使用API后端")

    def _call_via_cli(self, prompt: str, system: str) -> str:
        """通过命令行调用"""
        import subprocess
        if self.plugin_type == "claude_code":
            # Claude Code CLI
            result = subprocess.run(
                ["claude", "--print", prompt],
                capture_output=True, text=True, timeout=300
            )
            return result.stdout
        elif self.plugin_type == "codex":
            # Codex CLI
            result = subprocess.run(
                ["codex", "--print", prompt],
                capture_output=True, text=True, timeout=300
            )
            return result.stdout
        return ""


def create_llm_backend(config) -> LLMBackend:
    """根据配置创建LLM后端实例"""
    backend = config.backend.lower()

    if backend in ("lmstudio", "ollama", "openai"):
        return OpenAICompatibleBackend(config)
    elif backend == "claude":
        return ClaudeBackend(config)
    elif backend in ("claude_code", "codex"):
        return VSCodePluginBackend(config)
    else:
        logger.warning(f"未知后端 '{backend}'，降级为OpenAI兼容模式")
        return OpenAICompatibleBackend(config)
