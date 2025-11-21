# pyright: standard

from pathlib import Path
from typing import Any
from unittest import mock

from openai.types.chat import ChatCompletionChunk

from aico.core.llm_executor import _handle_unified_streaming


def create_mock_chunk(content: str | None, usage_data: dict[str, Any] | None = None) -> Any:
    """
    Creates a MagicMock that mimics a ChatCompletionChunk.
    Real Pydantic models are too strict for testing dynamic OpenRouter fields like 'cost'.
    """
    chunk = mock.MagicMock(spec=ChatCompletionChunk)

    if content is not None:
        container = mock.MagicMock()
        container.delta = mock.MagicMock(content=content, reasoning_content=None)
        chunk.choices = [container]
    else:
        # Usage chunk typically has empty choices
        chunk.choices = []

    if usage_data:
        usage_mock = mock.MagicMock()
        usage_mock.prompt_tokens = usage_data.get("prompt_tokens", 0)
        usage_mock.completion_tokens = usage_data.get("completion_tokens", 0)
        usage_mock.total_tokens = usage_data.get("total_tokens", 0)

        # Dictionary lookups for recursive Mocks
        usage_mock.prompt_tokens_details = mock.MagicMock()
        if "prompt_tokens_details" in usage_data:
            usage_mock.prompt_tokens_details.cached_tokens = usage_data["prompt_tokens_details"].get("cached_tokens")
        else:
            usage_mock.prompt_tokens_details.cached_tokens = None

        usage_mock.completion_tokens_details = mock.MagicMock()
        if "completion_tokens_details" in usage_data:
            usage_mock.completion_tokens_details.reasoning_tokens = usage_data["completion_tokens_details"].get(
                "reasoning_tokens"
            )
        else:
            usage_mock.completion_tokens_details.reasoning_tokens = None

        # Custom field
        usage_mock.cost = usage_data.get("cost")

        chunk.usage = usage_mock
    else:
        chunk.usage = None

    return chunk


def test_handle_unified_streaming_openai_native(tmp_path: Path) -> None:
    with mock.patch("aico.core.provider_router.create_client") as mock_create_client:
        mock_client = mock.MagicMock()
        mock_create_client.return_value = (mock_client, "gpt-4o", {})

        # Simulate stream: content chunk, then usage chunk
        mock_stream = [
            create_mock_chunk("Hello "),
            create_mock_chunk("World"),
            create_mock_chunk(
                None,
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "prompt_tokens_details": {"cached_tokens": 2},
                },
            ),
        ]
        mock_client.chat.completions.create.return_value = iter(mock_stream)

        # Call
        content, _, usage, cost = _handle_unified_streaming("gpt-4o", {}, [], tmp_path)

        assert content == "Hello World"
        assert usage is not None
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 5
        assert usage.cached_tokens == 2
        assert cost is None  # No cost in native OpenAI without external logic


def test_handle_unified_streaming_openrouter(tmp_path: Path) -> None:
    with mock.patch("aico.core.provider_router.create_client") as mock_create_client:
        mock_client = mock.MagicMock()
        # create_client returns extra_body used for OpenRouter
        mock_create_client.return_value = (
            mock_client,
            "anthropic/claude-3-opus",
            {"extra_body": {"usage": {"include": True}}},
        )

        mock_stream = [
            create_mock_chunk("Test"),
            create_mock_chunk(
                None,
                {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                    "cost": 0.004,  # OpenRouter extra field
                },
            ),
        ]
        mock_client.chat.completions.create.return_value = iter(mock_stream)

        content, _, usage, cost = _handle_unified_streaming("openrouter/anthropic/claude-3-opus", {}, [], tmp_path)

        assert content == "Test"
        assert usage is not None
        assert usage.prompt_tokens == 20
        assert usage.cost == 0.004
        assert cost == 0.004

        # Verify extra_body was passed
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["extra_body"] == {"usage": {"include": True}}
