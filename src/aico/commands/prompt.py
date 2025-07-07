import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from regex import regex
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.text import Text

from aico.aico_live_render import AicoLiveRender
from aico.diffing import (
    generate_display_content,
    generate_unified_diff,
    process_llm_response_stream,
)
from aico.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    DerivedContent,
    FileContents,
    FileHeader,
    LiteLLMChoiceContainer,
    LiteLLMUsage,
    LLMChatMessage,
    Mode,
    ProcessedDiffBlock,
    SessionData,
    TokenUsage,
    UnparsedBlock,
    UserChatMessage,
    WarningMessage,
)
from aico.prompts import ALIGNMENT_PROMPTS, DIFF_MODE_INSTRUCTIONS
from aico.utils import (
    build_original_file_contents,
    calculate_and_display_cost,
    get_active_history,
    is_input_terminal,
    is_terminal,
    load_session,
    reconstruct_historical_messages,
    save_session,
)


def _build_token_usage(usage: LiteLLMUsage) -> TokenUsage | None:
    """
    Converts a litellm usage object to our TokenUsage model.
    """
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


def _handle_unified_streaming(
    model_name: str,
    chat_history: list[ChatMessageHistoryItem],
    original_file_contents: FileContents,
    messages: list[LLMChatMessage],
    session_root: Path,
) -> tuple[str, str | None, TokenUsage | None, float | None]:
    """
    Handles the streaming logic for all modes, attempting to render diffs live,
    and collecting all warnings to display at the end.
    """
    import litellm

    full_llm_response_buffer: str = ""
    token_usage: TokenUsage | None = None
    live: Live | None = None

    rich_spinner: Spinner = Spinner("dots", "Generating response...")
    if is_terminal():
        live = Live(console=Console(), auto_refresh=True)
        # Scrolling to the end automatically by using a custom LiveRender
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
        for chunk in stream:
            delta, token_usage, reasoning_content = _process_chunk(chunk)
            if delta:
                full_llm_response_buffer += delta

                # Re-process the entire buffer on each chunk to get an updated stream of renderables.
                # This delegates all complex parsing and stateful logic to the diffing engine.
                stream_processor = process_llm_response_stream(
                    original_file_contents, full_llm_response_buffer, session_root
                )
                renderables: list[Markdown | Text] = []

                for item in stream_processor:
                    match item:
                        case str() as text:
                            # Render conversational text.
                            renderables.append(Markdown(text))
                        case UnparsedBlock(text=block_text):
                            # Render unparsed/failed blocks as plain text to avoid markdown artifacts.
                            renderables.append(Text(block_text, no_wrap=True))
                        case FileHeader(llm_file_path=path):
                            renderables.append(Markdown(f"File: `{path}`\n"))
                        case ProcessedDiffBlock(unified_diff=diff):
                            renderables.append(Markdown(f"```diff\n{diff}```\n"))
                        case WarningMessage(text=warning):
                            renderables.append(Markdown(f"⚠️ {warning}\n"))
                        case _:
                            pass

                live.update(Group(*renderables), refresh=True)

            elif not full_llm_response_buffer and reasoning_content:
                # If no delta but reasoning content, display the header (bold words) of the reasoning
                header = regex.search(r"^\*\*(.*?)\*\*", reasoning_content, regex.MULTILINE)
                if header and header.group(1):
                    rich_spinner.update(text=header.group(1))
        live.stop()
    else:
        for chunk in stream:
            delta, token_usage, _ = _process_chunk(chunk)
            if delta:
                full_llm_response_buffer += delta

    if (usage := getattr(stream, "usage", None)) and not token_usage and isinstance(usage, LiteLLMUsage):
        token_usage = _build_token_usage(usage)

    # Process the final response to collect and display warnings
    if full_llm_response_buffer:
        # The stream processor is now self-contained for state, so we can call it directly.
        processed_stream = process_llm_response_stream(original_file_contents, full_llm_response_buffer, session_root)
        warnings_to_display = [item.text for item in processed_stream if isinstance(item, WarningMessage)]
        if warnings_to_display:
            # Add a newline to separate from live content if necessary
            if is_terminal():
                print()
            console = Console(stderr=True)
            console.print("[yellow]Warnings:[/yellow]")
            for warning in warnings_to_display:
                console.print(f"[yellow]{warning}[/yellow]")

    final_display_content = generate_display_content(original_file_contents, full_llm_response_buffer, session_root)

    message_cost: float | None = None
    if token_usage:
        message_cost = calculate_and_display_cost(token_usage, model_name, chat_history)

    return full_llm_response_buffer, final_display_content, token_usage, message_cost


def _build_messages(
    session_data: SessionData,
    system_prompt: str,
    prompt_text: str,
    piped_content: str | None,
    mode: Mode,
    original_file_contents: FileContents,
    passthrough: bool,
) -> list[LLMChatMessage]:
    messages: list[LLMChatMessage] = []

    active_history = get_active_history(session_data)

    if passthrough:
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.extend(reconstruct_historical_messages(active_history))
        messages.append({"role": "user", "content": prompt_text})
        return messages

    # --- Standard (non-passthrough) logic ---
    if mode == Mode.DIFF:
        system_prompt += DIFF_MODE_INSTRUCTIONS

    user_prompt_parts: list[str] = []
    if original_file_contents:
        context_str = "<context>\n"
        for relative_path_str, content in original_file_contents.items():
            context_str += f'  <file path="{relative_path_str}">\n{content}\n</file>\n'
        context_str += "</context>\n"
        user_prompt_parts.append(context_str)

    if piped_content:
        user_prompt_parts.append(f"<stdin_content>\n{piped_content}\n</stdin_content>\n")

    user_prompt_parts.append(f"<prompt>\n{prompt_text}\n</prompt>")
    user_prompt_xml = "".join(user_prompt_parts)

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.extend(reconstruct_historical_messages(active_history))

    if mode in ALIGNMENT_PROMPTS:
        messages.extend([{"role": msg.role, "content": msg.content} for msg in ALIGNMENT_PROMPTS[mode]])

    messages.append({"role": "user", "content": user_prompt_xml})

    return messages


def _invoke_llm_logic(
    cli_prompt_text: str | None,
    system_prompt: str,
    mode: Mode,
    passthrough: bool,
    model: str | None,
) -> None:
    """
    Core logic for invoking the LLM that can be shared by all command wrappers.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent
    timestamp = datetime.now(UTC).isoformat()
    model_name = model or session_data.model

    primary_prompt: str
    secondary_piped_content: str | None = None
    piped_input: str | None = None
    if not is_input_terminal():
        content = sys.stdin.read()
        if content:
            piped_input = content

    if cli_prompt_text and piped_input:
        primary_prompt = cli_prompt_text
        secondary_piped_content = piped_input
    elif piped_input:
        primary_prompt = piped_input
    elif cli_prompt_text:
        primary_prompt = cli_prompt_text
    else:
        # No input from CLI or pipe, prompt interactively
        primary_prompt = Prompt.ask("Prompt")
        if not primary_prompt.strip():
            print("Error: Prompt is required.", file=sys.stderr)
            raise typer.Exit(code=1)

    original_file_contents: FileContents
    if passthrough:
        original_file_contents = {}
    else:
        original_file_contents = build_original_file_contents(
            context_files=session_data.context_files, session_root=session_root
        )

    messages = _build_messages(
        session_data=session_data,
        system_prompt=system_prompt,
        prompt_text=primary_prompt,
        piped_content=secondary_piped_content,
        mode=mode,
        original_file_contents=original_file_contents,
        passthrough=passthrough,
    )

    llm_response_content: str = ""
    display_content: str | None = None
    token_usage: TokenUsage | None = None
    message_cost: float | None = None
    duration_ms: int = -1

    try:
        start_time = time.monotonic()
        (
            llm_response_content,
            display_content,
            token_usage,
            message_cost,
        ) = _handle_unified_streaming(
            model_name, session_data.chat_history, original_file_contents, messages, session_root=session_root
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)
    except Exception as e:
        # Specific error handling can be improved in handlers if needed
        print(f"Error calling LLM API: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from e

    # 6. Process Output for Storage and Non-TTY
    # The `display_content` is already generated by the streaming handler.
    # We only need to generate the `unified_diff` for saving and non-TTY output.
    unified_diff = generate_unified_diff(original_file_contents, llm_response_content, session_root)

    # 7. Update State & Save
    assistant_response_timestamp = datetime.now(UTC).isoformat()
    derived_content: DerivedContent | None = None

    if unified_diff or (display_content and display_content != llm_response_content):
        # To save space, only store display_content if it's different from the raw content
        optimized_display_content = display_content if display_content != llm_response_content else None
        derived_content = DerivedContent(unified_diff=unified_diff, display_content=optimized_display_content)

    session_data.chat_history.append(
        UserChatMessage(
            role="user",
            content=primary_prompt,
            piped_content=secondary_piped_content,
            mode=mode,
            timestamp=timestamp,
            passthrough=passthrough,
        )
    )
    session_data.chat_history.append(
        AssistantChatMessage(
            role="assistant",
            content=llm_response_content,
            mode=mode,
            token_usage=token_usage,
            cost=message_cost,
            model=model_name,
            timestamp=assistant_response_timestamp,
            duration_ms=duration_ms,
            derived=derived_content,
        )
    )

    save_session(session_file, session_data)

    # 8. Print Final Output
    # This phase handles non-interactive output. All interactive output is handled
    # by the streaming functions.
    if not is_terminal():
        if passthrough:
            print(llm_response_content)
        else:
            if mode == Mode.DIFF:
                # Strict Contract: For 'edit', always print the diff, even if empty.
                # Warnings have already been sent to stderr.
                print(unified_diff or "", end="")
            else:  # Mode.CONVERSATION or Mode.RAW
                # Flexible Contract: For 'ask' and 'prompt', prioritize a valid diff,
                # but fall back to the display_content for conversations or errors.
                if unified_diff:
                    print(unified_diff, end="")
                elif display_content:
                    print(display_content, end="")


def ask(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[
        str, typer.Option(help="The system prompt to guide the AI.")
    ] = "You are an expert pair programmer.",
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Have a conversation with the AI for planning and discussion.
    """
    _invoke_llm_logic(cli_prompt_text, system_prompt, Mode.CONVERSATION, passthrough, model)


def edit(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[
        str, typer.Option(help="The system prompt to guide the AI.")
    ] = "You are an expert pair programmer.",
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Generate code modifications as a unified diff.
    """
    _invoke_llm_logic(cli_prompt_text, system_prompt, Mode.DIFF, passthrough, model)


def prompt(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[
        str, typer.Option(help="The system prompt to guide the AI.")
    ] = "You are an expert pair programmer.",
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Send a raw prompt directly to the AI with minimal formatting.
    """
    _invoke_llm_logic(cli_prompt_text, system_prompt, Mode.RAW, passthrough, model)
