import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, override

from aico.llm.providers.base import EMPTY_MAP, LLMProvider, LLMRequestConfig, NormalizedChunk
from aico.llm.providers.utils import get_env_var_or_fail, parse_standard_openai_chunk

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionChunk


class OpenAIProvider(LLMProvider):
    @override
    def configure_request(self, model_id: str, extra_params: Mapping[str, str] = EMPTY_MAP) -> LLMRequestConfig:
        api_key = get_env_var_or_fail("OPENAI_API_KEY", "OpenAI")
        base_url = os.getenv("OPENAI_BASE_URL")  # Use client default if None

        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)

        kwargs: dict[str, object] = {}
        if "reasoning_effort" in extra_params:
            kwargs["reasoning_effort"] = extra_params["reasoning_effort"]

        return LLMRequestConfig(client=client, model_id=model_id, extra_kwargs=kwargs)

    @override
    def process_chunk(self, chunk: "ChatCompletionChunk") -> NormalizedChunk:
        return parse_standard_openai_chunk(chunk)
