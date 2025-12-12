# pyright: standard

from pathlib import Path
from typing import Any
from unittest import mock

from aico.llm.executor import _handle_unified_streaming, extract_reasoning_header
from aico.llm.providers.base import LLMProvider, NormalizedChunk
from aico.models import TokenUsage


def create_mock_chunk(content: str | None, usage_data: dict[str, Any] | None = None) -> Any:
    """
    Creates a MagicMock that mimics a ChatCompletionChunk.
    """
    chunk = mock.MagicMock()

    if content is not None:
        container = mock.MagicMock()
        container.delta = mock.MagicMock(
            content=content,
            reasoning_content=None,
            reasoning=None,
            reasoning_details=None,
        )
        chunk.choices = [container]

    if usage_data:
        usage_mock = mock.MagicMock()
        usage_mock.prompt_tokens = usage_data.get("prompt_tokens", 0)
        usage_mock.completion_tokens = usage_data.get("completion_tokens", 0)
        usage_mock.total_tokens = usage_data.get("total_tokens", 0)
        usage_mock.cost = usage_data.get("cost")
        chunk.usage = usage_mock
    else:
        chunk.usage = None

    return chunk


def test_handle_unified_streaming_openai(tmp_path: Path):
    # GIVEN a mock provider
    mock_provider = mock.MagicMock(spec=LLMProvider)
    mock_client = mock.MagicMock()
    mock_provider.configure_request.return_value = (mock_client, "gpt-4o", {})

    mock_stream = [
        create_mock_chunk("Hello "),
        create_mock_chunk("World"),
        create_mock_chunk(None, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
    ]
    mock_client.chat.completions.create.return_value = iter(mock_stream)

    mock_provider.process_chunk.side_effect = [
        NormalizedChunk(content="Hello "),
        NormalizedChunk(content="World"),
        NormalizedChunk(token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)),
    ]

    # WHEN
    content, _, usage, cost = _handle_unified_streaming(mock_provider, "gpt-4o", {}, [], tmp_path)

    # THEN
    assert content == "Hello World"
    assert usage is not None
    assert usage.prompt_tokens == 10
    assert cost is None


def test_handle_unified_streaming_openrouter(tmp_path: Path):
    # GIVEN a mock provider
    mock_provider = mock.MagicMock(spec=LLMProvider)
    mock_client = mock.MagicMock()
    mock_provider.configure_request.return_value = (
        mock_client,
        "claude-3-opus",
        {"extra_body": {"usage": {"include": True}}},
    )

    mock_stream = [
        create_mock_chunk("Test"),
        create_mock_chunk(None, {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30, "cost": 0.004}),
    ]
    mock_client.chat.completions.create.return_value = iter(mock_stream)

    mock_provider.process_chunk.side_effect = [
        NormalizedChunk(content="Test"),
        NormalizedChunk(token_usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30), cost=0.004),
    ]

    # WHEN
    content, _, usage, cost = _handle_unified_streaming(mock_provider, "claude-3-opus", {}, [], tmp_path)

    # THEN
    assert content == "Test"
    assert usage is not None
    assert usage.prompt_tokens == 20
    assert cost == 0.004


def test_openai_provider_process_chunk_reasoning():
    from aico.llm.providers.openai import OpenAIProvider

    provider = OpenAIProvider()

    # Standard reasoning
    chunk = create_mock_chunk("")
    chunk.choices[0].delta.reasoning = "DeepSeek thinking"
    result = provider.process_chunk(chunk)
    assert result.reasoning == "DeepSeek thinking"

    # Legacy reasoning_content
    chunk = create_mock_chunk("")
    chunk.choices[0].delta.reasoning_content = "Legacy thinking"
    result = provider.process_chunk(chunk)
    assert result.reasoning == "Legacy thinking"

    # Reasoning details text
    chunk = create_mock_chunk("")
    detail_text = mock.MagicMock()
    detail_text.type = "reasoning.text"
    detail_text.text = "Step 1"
    chunk.choices[0].delta.reasoning_details = [detail_text]
    result = provider.process_chunk(chunk)
    assert result.reasoning == "Step 1"

    # Reasoning details summary
    chunk = create_mock_chunk("")
    detail_summary = mock.MagicMock()
    detail_summary.type = "reasoning.summary"
    detail_summary.summary = "Summary"
    chunk.choices[0].delta.reasoning_details = [detail_summary]
    result = provider.process_chunk(chunk)
    assert result.reasoning == "Summary"

    # Mixed + ignore unknown
    chunk = create_mock_chunk("")
    chunk.choices[0].delta.reasoning = "Base. "
    detail1 = mock.MagicMock(type="reasoning.text", text="Detail1.")
    detail_ignore = mock.MagicMock(type="reasoning.ignored")
    chunk.choices[0].delta.reasoning_details = [detail1, detail_ignore]
    result = provider.process_chunk(chunk)
    assert result.reasoning == "Base. Detail1."


def test_extract_reasoning_header() -> None:
    # Single Markdown header
    assert extract_reasoning_header("### Planning\nNext steps") == "Planning"

    # Single bold
    assert extract_reasoning_header("**Analysis** in progress") == "Analysis"

    # Multiple headers, last wins
    assert extract_reasoning_header("## First\n### Second\n**Final**") == "Final"

    # Incremental across "chunks"
    buffer1 = "### Plan"
    buffer2 = buffer1 + "\n**Exec**"
    assert extract_reasoning_header(buffer2) == "Exec"

    # No match
    assert extract_reasoning_header("Plain text without headers") is None

    # Malformed/incomplete
    assert extract_reasoning_header("**Unclosed") is None
    assert extract_reasoning_header("#### ") is None  # Empty header

    # Edge: trailing stars
    assert extract_reasoning_header("**Bold***") == "Bold"
