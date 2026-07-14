"""Remote API LLM provider.

Supports OpenAI, Anthropic (Claude), DeepSeek, Azure OpenAI, and any
OpenAI-compatible API endpoint. Routes to the appropriate SDK based on
provider name.
"""
import base64
from pathlib import Path
from typing import List

from .base import BaseLLMProvider, LLMResponse, Message


class APILLMProvider(BaseLLMProvider):
    """Provider for remote API-based LLM services.

    Supported providers:
    - 'openai': GPT-4o, GPT-4-vision, etc.
    - 'anthropic': Claude 3.5 Sonnet, Claude 3 Opus, etc.
    - 'deepseek': DeepSeek-V3, DeepSeek-R1
    - 'azure': Azure OpenAI
    - 'custom': Any OpenAI-compatible endpoint

    For Anthropic, uses the anthropic SDK with native vision support.
    For all others, uses the openai SDK.
    """

    def __init__(self, config):
        super().__init__(config)
        self._backend = self._detect_backend(config)
        if self._backend == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=config.api_key)
        else:
            from openai import OpenAI
            kwargs = {"api_key": config.api_key}
            if config.base_url:
                kwargs["base_url"] = config.base_url
            self._client = OpenAI(**kwargs)

    @staticmethod
    def _detect_backend(config) -> str:
        """Detect which SDK backend to use based on provider/model."""
        model_lower = config.model_id.lower()
        base_lower = config.base_url.lower() if config.base_url else ""

        if "anthropic" in base_lower or "claude" in model_lower:
            return "anthropic"
        if "deepseek" in base_lower or "deepseek" in model_lower:
            return "openai"  # DeepSeek uses OpenAI-compatible API
        if "azure" in base_lower:
            return "azure"
        return "openai"

    def chat(self, messages: List[Message], temperature: float = 0.1,
             max_tokens: int = 4000) -> LLMResponse:
        try:
            if self._backend == "anthropic":
                return self._chat_anthropic(messages, temperature, max_tokens)
            return self._chat_openai(messages, temperature, max_tokens)
        except Exception as exc:
            return LLMResponse(text="", success=False, error=str(exc))

    def _chat_openai(self, messages: List[Message], temperature: float,
                     max_tokens: int) -> LLMResponse:
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

    def _chat_anthropic(self, messages: List[Message], temperature: float,
                        max_tokens: int) -> LLMResponse:
        # Anthropic uses a different message format
        system_msg = ""
        user_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content if isinstance(m.content, str) else str(m.content)
            else:
                user_messages.append({"role": m.role, "content": m.content})

        kwargs = {
            "model": self.config.model_id,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = self._client.messages.create(**kwargs)
        text = response.content[0].text if response.content else ""
        return LLMResponse(text=text, success=True, raw=response)

    def chat_with_image(self, prompt: str, image_path: Path,
                        temperature: float = 0.1,
                        max_tokens: int = 3000) -> LLMResponse:
        try:
            image_data = base64.b64encode(
                Path(image_path).read_bytes()
            ).decode("utf-8")
            suffix = Path(image_path).suffix.lstrip(".").lower()
            mime = f"image/{suffix if suffix != 'jpg' else 'jpeg'}"

            if self._backend == "anthropic":
                content = [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": image_data,
                        },
                    },
                ]
                response = self._client.messages.create(
                    model=self.config.model_id,
                    messages=[{"role": "user", "content": content}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                text = response.content[0].text if response.content else ""
                return LLMResponse(text=text, success=True, raw=response)

            # OpenAI-compatible vision
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
