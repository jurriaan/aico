import os
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from aico.llm.providers.base import NormalizedChunk
from aico.models import TokenUsage

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionChunk
    from openai.types.completion_usage import CompletionUsage


@runtime_checkable
class ReasoningSummary(Protocol):
    type: str
    summary: str


@runtime_checkable
class ReasoningText(Protocol):
    type: str
    text: str


def _build_token_usage(usage: "CompletionUsage") -> TokenUsage:
    # Pydantic models from OpenAI SDK, but safeguard access
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)

    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost: float | None = None

    if prompt_details:
        cached_tokens = getattr(prompt_details, "cached_tokens", None)  # pyright: ignore[reportAny]

    if completion_details:
        reasoning_tokens = getattr(completion_details, "reasoning_tokens", None)  # pyright: ignore[reportAny]

    # OpenRouter custom field 'cost' injected into the usage object
    cost_val = getattr(usage, "cost", None)
    if isinstance(cost_val, float | int):
        cost = float(cost_val)

    return TokenUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
        cost=cost,
    )


def get_env_var_or_fail(var_name: str, provider_display_name: str) -> str:
    val = os.getenv(var_name)
    if not val:
        raise ValueError(f"{provider_display_name} requires the environment variable '{var_name}' to be set.")
    return val


def parse_standard_openai_chunk(chunk: "ChatCompletionChunk") -> NormalizedChunk:
    token_usage: TokenUsage | None = None

    # Check for content delta
    content: str | None = None
    reasoning: str | None = None

    if chunk.choices:
        choice = chunk.choices[0]
        delta = choice.delta
        content = delta.content

        reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)

        if details := getattr(delta, "reasoning_details", None):
            for detail in details:  # pyright: ignore[reportAny]
                match detail:
                    case ReasoningText(type="reasoning.text", text=str(text)):
                        reasoning = (reasoning or "") + text
                    case ReasoningSummary(type="reasoning.summary", summary=str(summary)):
                        reasoning = (reasoning or "") + summary
                    case _:  # pyright: ignore[reportAny]
                        pass

    # Check for usage block (typically last chunk in OpenRouter/OpenAI streams)
    if chunk.usage:
        token_usage = _build_token_usage(chunk.usage)

    return NormalizedChunk(
        content=content,
        reasoning=reasoning,
        token_usage=token_usage,
        cost=None,
    )
