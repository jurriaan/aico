import math
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import regex
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

from aico.console import (
    calculate_and_display_cost,
    is_terminal,
    render_display_items_to_rich,
)
from aico.diffing.stream_processor import (
    analyze_response,
)
from aico.fs import get_context_files_with_metadata
from aico.live_render import AicoLiveRender
from aico.llm.prompt_helpers import reconstruct_historical_messages
from aico.llm.providers.base import LLMProvider
from aico.llm.router import get_provider_for_model
from aico.models import (
    ChatMessageHistoryItem,
    DisplayItem,
    FileContents,
    InteractionResult,
    LLMChatMessage,
    MetadataFileContents,
    Mode,
    SessionData,
    TokenUsage,
)
from aico.prompts import (
    ALIGNMENT_PROMPTS,
    DIFF_MODE_INSTRUCTIONS,
    FLOATING_CONTEXT_ANCHOR,
    FLOATING_CONTEXT_INTRO,
    STATIC_CONTEXT_ANCHOR,
    STATIC_CONTEXT_INTRO,
)
from aico.session import build_active_context

if TYPE_CHECKING:
    pass


def _format_file_block(files: MetadataFileContents, intro_text: str, anchor_text: str) -> list[LLMChatMessage]:
    """Helper to generate standard context blocks."""
    if not files:
        return []

    xml_content = "<context>\n"
    for path, meta in files.items():
        xml_content += f'  <file path="{path}">\n{meta.content}\n</file>\n'
    xml_content += "</context>\n"

    return [
        {"role": "user", "content": f"{intro_text}\n\n{xml_content}"},
        {"role": "assistant", "content": anchor_text},
    ]


def _build_messages(
    active_history: list[ChatMessageHistoryItem],
    system_prompt: str,
    prompt_text: str,
    piped_content: str | None,
    mode: Mode,
    file_metadata: MetadataFileContents,
    passthrough: bool,
    no_history: bool,
) -> list[LLMChatMessage]:
    messages: list[LLMChatMessage] = []

    # --- 1. System Prompt ---
    if mode == Mode.DIFF:
        system_prompt += DIFF_MODE_INSTRUCTIONS

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    history_to_use = active_history if not no_history else []

    if passthrough:
        messages.extend(reconstruct_historical_messages(history_to_use))
        user_prompt = (
            (f"<stdin_content>\n{piped_content}\n</stdin_content>\n<prompt>\n{prompt_text}\n</prompt>")
            if piped_content is not None
            else f"{prompt_text}"
        )
        messages.append({"role": "user", "content": user_prompt})
        return messages

    # --- 2. Chronological Context Calculations ---
    def to_dt(iso_ts: str) -> datetime:
        if iso_ts.endswith("Z"):
            iso_ts = iso_ts[:-1] + "+00:00"
        return datetime.fromisoformat(iso_ts)

    # Horizon: Time of first message. If no history, we are at the start of time (everything is static).
    # We use a far future horizon for fresh sessions to ensure mtime < horizon is always True.
    horizon = to_dt(history_to_use[0].timestamp) if history_to_use else datetime(3000, 1, 1, tzinfo=UTC)

    static_files: MetadataFileContents = {}
    floating_files: MetadataFileContents = {}

    for path, meta in file_metadata.items():
        # Ceil mtime to prevent ISO precision inaccuracies
        file_time = datetime.fromtimestamp(math.ceil(meta.mtime), tz=UTC)
        if file_time < horizon:
            static_files[path] = meta
        else:
            floating_files[path] = meta

    # --- 3. Determine Splice Point ---
    # Default: Insert at the very end of history
    splice_idx = len(history_to_use)

    if floating_files:
        # Event Horizon: The moment the code became valid
        t_update = max(datetime.fromtimestamp(math.ceil(f.mtime), tz=UTC) for f in floating_files.values())

        # Scan for the first message that happened *after* the update
        for i, msg in enumerate(history_to_use):
            if to_dt(msg.timestamp) > t_update:
                splice_idx = i
                break

    # --- 4. Linear Assembly ---

    # A. Static Context (Ground Truth)
    messages.extend(_format_file_block(static_files, STATIC_CONTEXT_INTRO, STATIC_CONTEXT_ANCHOR))

    # B. History Part 1 (Before Edits)
    messages.extend(reconstruct_historical_messages(history_to_use[:splice_idx]))

    # C. Floating Context (The Update)
    messages.extend(_format_file_block(floating_files, FLOATING_CONTEXT_INTRO, FLOATING_CONTEXT_ANCHOR))

    # D. History Part 2 (After Edits)
    messages.extend(reconstruct_historical_messages(history_to_use[splice_idx:]))

    # --- 5. Final Alignment and User Prompt ---
    if mode in ALIGNMENT_PROMPTS:
        messages.extend([LLMChatMessage(role=msg.role, content=msg.content) for msg in ALIGNMENT_PROMPTS[mode]])

    user_prompt = (
        (f"<stdin_content>\n{piped_content}\n</stdin_content>\n<prompt>\n{prompt_text}\n</prompt>")
        if piped_content is not None
        else f"{prompt_text}"
    )
    messages.append({"role": "user", "content": user_prompt})

    return messages


def extract_reasoning_header(reasoning_buffer: str) -> str | None:
    """Extracts the last Markdown header (#) or bold (**text**) from the reasoning buffer for spinner."""
    matches = list(
        regex.finditer(
            r"(?:^#{1,6}\s+(?P<header>.+)$)|(?:^\*\*\s*(?P<bold>.+?)\s*\*\*)",
            reasoning_buffer,
            regex.MULTILINE,
        )
    )
    if matches:
        last_match = matches[-1]
        text = last_match.group("header") or last_match.group("bold")
        if text:
            return text.strip()
    return None


def _handle_unified_streaming(
    provider: LLMProvider,
    clean_model_id: str,
    extra_params: Mapping[str, str],
    original_file_contents: FileContents,
    messages: list[LLMChatMessage],
    session_root: Path,
) -> tuple[str, list[DisplayItem] | None, TokenUsage | None, float | None, str | None]:
    from openai.types.chat import (
        ChatCompletionMessageParam,
        ChatCompletionStreamOptionsParam,
    )

    full_llm_response_buffer: str = ""
    token_usage: TokenUsage | None = None
    exact_cost: float | None = None
    live: Live | None = None

    # Create configured client and get resolved model/params
    config = provider.configure_request(clean_model_id, extra_params)
    client, actual_model, extra_kwargs = config.client, config.model_id, config.extra_kwargs

    # OpenAI native usage requirement
    stream_options: ChatCompletionStreamOptionsParam = {"include_usage": True}

    spinner_text = f"Generating response ({actual_model})..."
    rich_spinner: Spinner = Spinner("dots", spinner_text)
    if is_terminal():
        live = Live(console=Console(), auto_refresh=True)
        live._live_render = AicoLiveRender(live.get_renderable())  # pyright: ignore[reportPrivateUsage]
        live.start()
        live.update(rich_spinner, refresh=True)

    stream = client.chat.completions.create(
        model=actual_model,
        messages=cast(list[ChatCompletionMessageParam], messages),
        stream=True,
        stream_options=stream_options,
        **extra_kwargs,  # pyright: ignore[reportAny]
    )

    if live:
        reasoning_buffer = ""
        for chunk in stream:
            normalized_chunk = provider.process_chunk(chunk)
            if normalized_chunk.content:
                full_llm_response_buffer += normalized_chunk.content

                _, display_items, _ = analyze_response(original_file_contents, full_llm_response_buffer, session_root)
                renderable_group = render_display_items_to_rich(display_items)

                live.update(renderable_group, refresh=True)

            if normalized_chunk.token_usage:
                token_usage = normalized_chunk.token_usage
            if normalized_chunk.cost is not None:
                exact_cost = normalized_chunk.cost

            elif not full_llm_response_buffer and normalized_chunk.reasoning:
                reasoning_buffer += normalized_chunk.reasoning
                if header := extract_reasoning_header(reasoning_buffer):
                    rich_spinner.update(text=header)
        live.stop()
    else:
        for chunk in stream:
            normalized_chunk = provider.process_chunk(chunk)

            if normalized_chunk.content:
                full_llm_response_buffer += normalized_chunk.content

            if normalized_chunk.token_usage:
                token_usage = normalized_chunk.token_usage
            if normalized_chunk.cost is not None:
                exact_cost = normalized_chunk.cost

    # Warnings collection and unified analysis
    unified_diff: str | None = None
    final_display_items: list[DisplayItem] | None = None
    warnings_to_display: list[str] = []

    if full_llm_response_buffer:
        unified_diff, final_display_items, warnings_to_display = analyze_response(
            original_file_contents, full_llm_response_buffer, session_root
        )

        if warnings_to_display:
            if is_terminal():
                print()
            console = Console(stderr=True)
            console.print("[yellow]Warnings:[/yellow]")
            for warning in warnings_to_display:
                console.print(f"[yellow]{warning}[/yellow]")

    return full_llm_response_buffer, final_display_items, token_usage, exact_cost, unified_diff


def execute_interaction(
    session_data: SessionData,
    system_prompt: str,
    prompt_text: str,
    piped_content: str | None,
    mode: Mode,
    passthrough: bool,
    no_history: bool,
    session_root: Path,
    model_override: str | None,
) -> InteractionResult:
    """
    Execute a single interaction with the LLM, handling streaming and rendering.
    Returns an InteractionResult object with structured fields.
    """
    context = build_active_context(session_data)
    model_name = model_override or context["model"]
    provider, clean_model_id, extra_params = get_provider_for_model(model_name)

    if passthrough:
        file_metadata: MetadataFileContents = {}
        original_file_contents: FileContents = {}
    else:
        file_metadata = get_context_files_with_metadata(context["context_files"], session_root)
        original_file_contents = {p: meta.content for p, meta in file_metadata.items()}

    messages = _build_messages(
        active_history=context["active_history"],
        system_prompt=system_prompt,
        prompt_text=prompt_text,
        piped_content=piped_content,
        mode=mode,
        file_metadata=file_metadata,
        passthrough=passthrough,
        no_history=no_history,
    )

    start_time = time.monotonic()
    llm_response_content, display_items, token_usage, exact_cost, unified_diff = _handle_unified_streaming(
        provider, clean_model_id, extra_params, original_file_contents, messages, session_root
    )
    duration_ms = int((time.monotonic() - start_time) * 1000)

    message_cost: float | None = None
    if token_usage:
        message_cost = calculate_and_display_cost(token_usage, model_name, session_data, exact_cost=exact_cost)

    return InteractionResult(
        content=llm_response_content,
        display_items=display_items,
        token_usage=token_usage,
        cost=message_cost,
        duration_ms=duration_ms,
        unified_diff=unified_diff,
    )
