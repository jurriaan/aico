# pyright: standard

from pathlib import Path
from typing import Any
from unittest import mock

from openai.types.chat import ChatCompletionChunk

from aico.core.llm_executor import _handle_unified_streaming, _process_chunk


def create_mock_chunk(content: str | None, usage_data: dict[str, Any] | None = None) -> Any:
    """
    Creates a MagicMock that mimics a ChatCompletionChunk.
    Real Pydantic models are too strict for testing dynamic OpenRouter fields like 'cost'.
    """
    chunk = mock.MagicMock(spec=ChatCompletionChunk)

    if content is not None:
        container = mock.MagicMock()
        # Explicitly set optional fields to None to avoid MagicMock autovivification
        # confusing the getattr() checks in _process_chunk
        container.delta = mock.MagicMock(
            content=content,
            reasoning_content=None,
            reasoning=None,
            reasoning_details=None,
        )
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


def test_process_chunk_reasoning_variants(tmp_path: Path) -> None:
    """
    Verifies that _process_chunk correctly extracts reasoning from various
    schema locations (standard fields, legacy fields, and complex details arrays).
    """
    # 1. Standard Field (e.g. DeepSeek)
    chunk_standard = create_mock_chunk("")
    chunk_standard.choices[0].delta.reasoning = "DeepSeek thinking"
    _, _, reasoning, _ = _process_chunk(chunk_standard)
    assert reasoning == "DeepSeek thinking"

    # 2. Legacy/Proxy Field
    chunk_legacy = create_mock_chunk("")
    chunk_legacy.choices[0].delta.reasoning = None
    chunk_legacy.choices[0].delta.reasoning_content = "Legacy thinking"
    _, _, reasoning, _ = _process_chunk(chunk_legacy)
    assert reasoning == "Legacy thinking"

    # 3. Reasoning Details (Text) - e.g. Anthropic
    chunk_details_text = create_mock_chunk("")
    detail_text = mock.MagicMock()
    detail_text.type = "reasoning.text"
    detail_text.text = "Step 1: Analyze"
    chunk_details_text.choices[0].delta.reasoning_details = [detail_text]

    _, _, reasoning, _ = _process_chunk(chunk_details_text)
    assert reasoning == "Step 1: Analyze"

    # 4. Reasoning Details (Summary) - e.g. O1/O3
    chunk_details_summary = create_mock_chunk("")
    detail_summary = mock.MagicMock()
    detail_summary.type = "reasoning.summary"
    detail_summary.summary = "Calculated the trajectory"
    chunk_details_summary.choices[0].delta.reasoning_details = [detail_summary]

    _, _, reasoning, _ = _process_chunk(chunk_details_summary)
    assert reasoning == "Calculated the trajectory"

    # 5. Concatenation (Mixed) & Ignoring unknown types
    chunk_mixed = create_mock_chunk("")
    chunk_mixed.choices[0].delta.reasoning = "Base reasoning. "

    detail_1 = mock.MagicMock()
    detail_1.type = "reasoning.text"
    detail_1.text = "Detail 1."

    detail_encrypted = mock.MagicMock()
    detail_encrypted.type = "reasoning.encrypted"  # Should be ignored
    detail_encrypted.text = "Secret"

    # Provide details list
    chunk_mixed.choices[0].delta.reasoning_details = [detail_1, detail_encrypted]

    _, _, reasoning, _ = _process_chunk(chunk_mixed)
    assert reasoning == "Base reasoning. Detail 1."


def test_extract_reasoning_header() -> None:
    from aico.core.llm_executor import extract_reasoning_header

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
