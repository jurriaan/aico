import os
from dataclasses import replace
from typing import TYPE_CHECKING, Any, override

from aico.llm.providers.base import LLMProvider, NormalizedChunk
from aico.llm.providers.utils import get_env_var_or_fail, parse_standard_openai_chunk

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletionChunk


class OpenRouterProvider(LLMProvider):
    @override
    def configure_request(self, model_id: str) -> tuple["OpenAI", str, dict[str, Any]]:  # pyright: ignore[reportExplicitAny]
        api_key = get_env_var_or_fail("OPENROUTER_API_KEY", "OpenRouter")
        base_url = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        return client, model_id, {"extra_body": {"usage": {"include": True}}}

    @override
    def process_chunk(self, chunk: "ChatCompletionChunk") -> NormalizedChunk:
        normalized = parse_standard_openai_chunk(chunk)

        # OpenRouter-specific cost injection
        if chunk.usage:
            cost_val = getattr(chunk.usage, "cost", None)
            if isinstance(cost_val, float | int):
                return replace(normalized, cost=float(cost_val))

        return normalized
