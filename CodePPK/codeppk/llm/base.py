"""Abstract LLM provider interface.

All providers (local, API, plugin) implement this interface, allowing
the automation engine to switch between them transparently.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union


@dataclass
class Message:
    """A chat message."""
    role: str  # user | assistant | system
    content: Union[str, List[dict]]  # str for text, list for multimodal


@dataclass
class LLMResponse:
    """Response from an LLM call."""
    text: str
    success: bool
    error: str = ""
    raw: object = None


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers.

    Implementations must support both text chat and multimodal (vision)
    calls, though some providers may delegate vision to a different model.
    """

    def __init__(self, config):
        from ..config import LLMConfig
        self.config: LLMConfig = config

    @abstractmethod
    def chat(self, messages: List[Message], temperature: float = 0.1,
             max_tokens: int = 4000) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of Message objects.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            LLMResponse with the generated text.
        """
        ...

    @abstractmethod
    def chat_with_image(self, prompt: str, image_path: Path,
                        temperature: float = 0.1,
                        max_tokens: int = 3000) -> LLMResponse:
        """Send a multimodal request with an image.

        Args:
            prompt: Text prompt.
            image_path: Path to the image file (jpg, png).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            LLMResponse with the generated text.
        """
        ...

    def simple_chat(self, prompt: str, temperature: float = 0.1,
                    max_tokens: int = 4000) -> str:
        """Convenience method: send a single text prompt, return text only."""
        response = self.chat(
            [Message(role="user", content=prompt)],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not response.success:
            raise RuntimeError(f"LLM call failed: {response.error}")
        return response.text
