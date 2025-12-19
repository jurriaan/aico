from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
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


@dataclass(slots=True, frozen=True)
class LLMRequestConfig:
    client: OpenAI
    model_id: str
    extra_kwargs: dict[str, Any]  # pyright: ignore[reportExplicitAny]


EMPTY_MAP: Mapping[str, str] = {}


class LLMProvider(ABC):
    @abstractmethod
    def configure_request(self, model_id: str, extra_params: Mapping[str, str] = EMPTY_MAP) -> LLMRequestConfig:
        """Returns the configured client, actual model name, and extra kwargs."""
        ...

    @abstractmethod
    def process_chunk(self, chunk: ChatCompletionChunk) -> NormalizedChunk:
        """Processes a raw chunk into a normalized structure."""
        ...
