import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import regex
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

from aico.aico_live_render import AicoLiveRender
from aico.core.files import get_context_file_contents
from aico.core.prompt_helpers import reconstruct_historical_messages
from aico.core.provider_router import get_provider_for_model
from aico.core.providers.base import LLMProvider
from aico.core.session_context import build_active_context
from aico.lib.diffing import (
    generate_display_items,
    generate_unified_diff,
    process_llm_response_stream,
)
from aico.lib.models import (
    ChatMessageHistoryItem,
    DisplayItem,
    FileContents,
    InteractionResult,
    LLMChatMessage,
    Mode,
    SessionData,
    TokenUsage,
    WarningMessage,
)
from aico.lib.ui import (
    calculate_and_display_cost,
    is_terminal,
    render_display_items_to_rich,
)
from aico.prompts import ALIGNMENT_PROMPTS, DIFF_MODE_INSTRUCTIONS

if TYPE_CHECKING:
    pass


def _build_messages(
    active_history: list[ChatMessageHistoryItem],
    system_prompt: str,
    prompt_text: str,
    piped_content: str | None,
    mode: Mode,
    original_file_contents: FileContents,
    passthrough: bool,
    no_history: bool,
) -> list[LLMChatMessage]:
    messages: list[LLMChatMessage] = []

    # --- 1. System Prompt ---
    if mode == Mode.DIFF:
        system_prompt += DIFF_MODE_INSTRUCTIONS

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # --- 2. Context Injection (Ground Truth) ---
    # We only do this if NOT in passthrough and if we actually have files.
    if not passthrough and original_file_contents:
        context_str = "<context>\n"
        for relative_path_str, content in original_file_contents.items():
            context_str += f'  <file path="{relative_path_str}">\n{content}\n</file>\n'
        context_str += "</context>\n"

        # The wrapper that enforces "Ground Truth"
        context_wrapper = (
            "The following XML block contains the CURRENT contents of the files in this session. "
            "This is the Ground Truth.\n\n"
            "Always refer to this block for the latest code state. "
            "If code blocks in the conversation history conflict with this block, ignore the history "
            "and use this block.\n\n"
            f"{context_str}"
        )

        messages.append({"role": "user", "content": context_wrapper})

        # The Anchor to lock it in and maintain User/Assistant turn structure
        messages.append(
            {
                "role": "assistant",
                "content": "I have read the current file state. I will use this block as the ground truth "
                + "for all code generation.",
            }
        )

    # --- 3. History Injection ---
    history_to_use: list[ChatMessageHistoryItem] = [] if no_history else active_history

    # Inject alignment prompts
    if mode in ALIGNMENT_PROMPTS:
        messages.extend(reconstruct_historical_messages(history_to_use))
        messages.extend([{"role": msg.role, "content": msg.content} for msg in ALIGNMENT_PROMPTS[mode]])
    else:
        messages.extend(reconstruct_historical_messages(history_to_use))

    # --- 4. Final User Prompt ---
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
    original_file_contents: FileContents,
    messages: list[LLMChatMessage],
    session_root: Path,
) -> tuple[str, list[DisplayItem] | None, TokenUsage | None, float | None]:
    from openai.types.chat import (
        ChatCompletionMessageParam,
        ChatCompletionStreamOptionsParam,
    )

    full_llm_response_buffer: str = ""
    token_usage: TokenUsage | None = None
    exact_cost: float | None = None
    live: Live | None = None

    # Create configured client and get resolved model/params
    client, actual_model, extra_kwargs = provider.configure_request(clean_model_id)

    # OpenAI native usage requirement
    stream_options: ChatCompletionStreamOptionsParam = {"include_usage": True}

    rich_spinner: Spinner = Spinner("dots", "Generating response...")
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

                display_items = generate_display_items(original_file_contents, full_llm_response_buffer, session_root)
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

    # Warnings collection
    if full_llm_response_buffer:
        processed_stream = process_llm_response_stream(original_file_contents, full_llm_response_buffer, session_root)
        warnings_to_display = [item.text for item in processed_stream if isinstance(item, WarningMessage)]
        if warnings_to_display:
            if is_terminal():
                print()
            console = Console(stderr=True)
            console.print("[yellow]Warnings:[/yellow]")
            for warning in warnings_to_display:
                console.print(f"[yellow]{warning}[/yellow]")

    final_display_items = generate_display_items(original_file_contents, full_llm_response_buffer, session_root)

    return full_llm_response_buffer, final_display_items or None, token_usage, exact_cost


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
    provider, clean_model_id = get_provider_for_model(model_name)

    if passthrough:
        original_file_contents: FileContents = {}
    else:
        original_file_contents = get_context_file_contents(context["context_files"], session_root)

    messages = _build_messages(
        active_history=context["active_history"],
        system_prompt=system_prompt,
        prompt_text=prompt_text,
        piped_content=piped_content,
        mode=mode,
        original_file_contents=original_file_contents,
        passthrough=passthrough,
        no_history=no_history,
    )

    start_time = time.monotonic()
    llm_response_content, display_items, token_usage, exact_cost = _handle_unified_streaming(
        provider, clean_model_id, original_file_contents, messages, session_root
    )
    duration_ms = int((time.monotonic() - start_time) * 1000)

    message_cost: float | None = None
    if token_usage:
        message_cost = calculate_and_display_cost(token_usage, model_name, session_data, exact_cost=exact_cost)

    unified_diff = generate_unified_diff(original_file_contents, llm_response_content, session_root)

    return InteractionResult(
        content=llm_response_content,
        display_items=display_items,
        token_usage=token_usage,
        cost=message_cost,
        duration_ms=duration_ms,
        unified_diff=unified_diff,
    )
