"""Local LLM provider (LM Studio, Ollama, etc.).

These run as OpenAI-compatible local servers, so we use the openai SDK
with a custom base_url. This is the default provider, matching the
existing PopPK_Agent approach.
"""
import base64
from pathlib import Path
from typing import List

from .base import BaseLLMProvider, LLMResponse, Message


class LocalLLMProvider(BaseLLMProvider):
    """Provider for local OpenAI-compatible LLM servers.

    Works with:
    - LM Studio (default: http://localhost:1234/v1)
    - Ollama (http://localhost:11434/v1)
    - llama-cpp-python server
    - vLLM
    - Any OpenAI-compatible local endpoint
    """

    def __init__(self, config):
        super().__init__(config)
        from openai import OpenAI
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "lm-studio",
        )

    def chat(self, messages: List[Message], temperature: float = 0.1,
             max_tokens: int = 4000) -> LLMResponse:
        try:
            formatted = [{"role": m.role, "content": m.content} for m in messages]
            response = self._client.chat.completions.create(
                model=self.config.model_id,
                messages=formatted,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return LLMResponse(
                text=response.choices[0].message.content,
                success=True,
                raw=response,
            )
        except Exception as exc:
            return LLMResponse(text="", success=False, error=str(exc))

    def chat_with_image(self, prompt: str, image_path: Path,
                        temperature: float = 0.1,
                        max_tokens: int = 3000) -> LLMResponse:
        try:
            image_data = base64.b64encode(
                Path(image_path).read_bytes()
            ).decode("utf-8")
            suffix = Path(image_path).suffix.lstrip(".").lower()
            mime = f"image/{suffix if suffix != 'jpg' else 'jpeg'}"
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}},
            ]
            response = self._client.chat.completions.create(
                model=self.config.model_id,
                messages=[{"role": "user", "content": content}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return LLMResponse(
                text=response.choices[0].message.content,
                success=True,
                raw=response,
            )
        except Exception as exc:
            return LLMResponse(text="", success=False, error=str(exc))
