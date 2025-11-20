import time
from pathlib import Path

import regex
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

from aico.aico_live_render import AicoLiveRender
from aico.lib.diffing import (
    generate_display_items,
    generate_unified_diff,
    process_llm_response_stream,
)
from aico.lib.models import (
    DisplayItem,
    FileContents,
    InteractionResult,
    LiteLLMChoiceContainer,
    LiteLLMUsage,
    LLMChatMessage,
    Mode,
    SessionData,
    TokenUsage,
    WarningMessage,
)
from aico.lib.session import build_original_file_contents
from aico.prompts import ALIGNMENT_PROMPTS, DIFF_MODE_INSTRUCTIONS
from aico.utils import (
    calculate_and_display_cost,
    get_active_history,
    is_terminal,
    reconstruct_historical_messages,
    render_display_items_to_rich,
)


def _build_token_usage(usage: LiteLLMUsage) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _process_chunk(chunk: object) -> tuple[str | None, TokenUsage | None, str | None]:
    token_usage: TokenUsage | None = None
    if (usage := getattr(chunk, "usage", None)) and isinstance(usage, LiteLLMUsage):
        token_usage = _build_token_usage(usage)
    if isinstance(chunk, LiteLLMChoiceContainer) and chunk.choices and (delta := chunk.choices[0].delta):
        return delta.content, token_usage, getattr(delta, "reasoning_content", None)
    return None, token_usage, None


def _build_messages(
    session_data: SessionData,
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
    active_history = [] if no_history else get_active_history(session_data)

    # Inject alignment prompts
    if mode in ALIGNMENT_PROMPTS:
        messages.extend(reconstruct_historical_messages(active_history))
        messages.extend([{"role": msg.role, "content": msg.content} for msg in ALIGNMENT_PROMPTS[mode]])
    else:
        messages.extend(reconstruct_historical_messages(active_history))

    # --- 4. Final User Prompt ---
    user_prompt = (
        (f"<stdin_content>\n{piped_content}\n</stdin_content>\n<prompt>\n{prompt_text}\n</prompt>")
        if piped_content is not None
        else f"{prompt_text}"
    )

    messages.append({"role": "user", "content": user_prompt})

    return messages


def _handle_unified_streaming(
    model_name: str,
    original_file_contents: FileContents,
    messages: list[LLMChatMessage],
    session_root: Path,
) -> tuple[str, list[DisplayItem] | None, TokenUsage | None]:
    import litellm

    full_llm_response_buffer: str = ""
    token_usage: TokenUsage | None = None
    live: Live | None = None

    rich_spinner: Spinner = Spinner("dots", "Generating response...")
    if is_terminal():
        live = Live(console=Console(), auto_refresh=True)
        live._live_render = AicoLiveRender(live.get_renderable())  # pyright: ignore[reportPrivateUsage]
        live.start()
        live.update(rich_spinner, refresh=True)

    stream = litellm.completion(  # pyright: ignore[reportUnknownMemberType]
        model=model_name,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )

    if live:
        reasoning_buffer = ""
        for chunk in stream:
            delta, token_usage, reasoning_content = _process_chunk(chunk)
            if delta:
                full_llm_response_buffer += delta

                display_items = generate_display_items(original_file_contents, full_llm_response_buffer, session_root)
                renderable_group = render_display_items_to_rich(display_items)

                live.update(renderable_group, refresh=True)

            elif not full_llm_response_buffer and reasoning_content:
                reasoning_buffer += reasoning_content
                headers = list(regex.finditer(r"^\*\*(.*?)\*\*", reasoning_buffer, regex.MULTILINE))
                if headers:
                    last_header_text = headers[-1].group(1)
                    if last_header_text:
                        rich_spinner.update(text=last_header_text)
        live.stop()
    else:
        for chunk in stream:
            delta, token_usage, _ = _process_chunk(chunk)
            if delta:
                full_llm_response_buffer += delta

    if (usage := getattr(stream, "usage", None)) and not token_usage and isinstance(usage, LiteLLMUsage):
        token_usage = _build_token_usage(usage)

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

    return full_llm_response_buffer, final_display_items or None, token_usage


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
    model_name = model_override or session_data.model

    if passthrough:
        original_file_contents: FileContents = {}
    else:
        original_file_contents = build_original_file_contents(
            context_files=session_data.context_files, session_root=session_root
        )

    messages = _build_messages(
        session_data=session_data,
        system_prompt=system_prompt,
        prompt_text=prompt_text,
        piped_content=piped_content,
        mode=mode,
        original_file_contents=original_file_contents,
        passthrough=passthrough,
        no_history=no_history,
    )

    start_time = time.monotonic()
    llm_response_content, display_items, token_usage = _handle_unified_streaming(
        model_name, original_file_contents, messages, session_root
    )
    duration_ms = int((time.monotonic() - start_time) * 1000)

    message_cost: float | None = None
    if token_usage:
        message_cost = calculate_and_display_cost(token_usage, model_name, session_data)

    unified_diff = generate_unified_diff(original_file_contents, llm_response_content, session_root)

    return InteractionResult(
        content=llm_response_content,
        display_items=display_items,
        token_usage=token_usage,
        cost=message_cost,
        duration_ms=duration_ms,
        unified_diff=unified_diff,
    )
