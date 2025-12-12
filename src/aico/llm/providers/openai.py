import os
from typing import TYPE_CHECKING, Any, override

from aico.llm.providers.base import LLMProvider, NormalizedChunk
from aico.llm.providers.utils import get_env_var_or_fail, parse_standard_openai_chunk

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletionChunk


class OpenAIProvider(LLMProvider):
    @override
    def configure_request(self, model_id: str) -> tuple["OpenAI", str, dict[str, Any]]:  # pyright: ignore[reportExplicitAny]
        api_key = get_env_var_or_fail("OPENAI_API_KEY", "OpenAI")
        base_url = os.getenv("OPENAI_BASE_URL")  # Use client default if None

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        return client, model_id, {}

    @override
    def process_chunk(self, chunk: "ChatCompletionChunk") -> NormalizedChunk:
        return parse_standard_openai_chunk(chunk)
