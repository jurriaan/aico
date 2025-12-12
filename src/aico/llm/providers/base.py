from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aico.models import TokenUsage

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletionChunk


@dataclass(slots=True, frozen=True)
class NormalizedChunk:
    content: str | None = None
    reasoning: str | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None


class LLMProvider(ABC):
    @abstractmethod
    def configure_request(self, model_id: str) -> tuple[OpenAI, str, dict[str, Any]]:  # pyright: ignore[reportExplicitAny]
        """Returns the configured client, actual model name, and extra kwargs."""
        ...

    @abstractmethod
    def process_chunk(self, chunk: ChatCompletionChunk) -> NormalizedChunk:
        """Processes a raw chunk into a normalized structure."""
        ...
