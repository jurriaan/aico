import sys
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Prompt

from aico.addons import register_addon_commands
from aico.diffing import (
    generate_display_content,
    generate_unified_diff,
)
from aico.history import history_app
from aico.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    FileContents,
    LastResponse,
    LiteLLMChoiceContainer,
    LiteLLMUsage,
    LLMChatMessage,
    Mode,
    SessionData,
    TokenUsage,
    UserChatMessage,
)
from aico.prompts import ALIGNMENT_PROMPTS, DIFF_MODE_INSTRUCTIONS
from aico.tokens import tokens_app
from aico.utils import (
    SESSION_FILE_NAME,
    calculate_and_display_cost,
    complete_files_in_context,
    get_relative_path_or_error,
    is_input_terminal,
    is_terminal,
    load_session,
    reconstruct_historical_messages,
    save_session,
)

app = typer.Typer()
app.add_typer(history_app, name="history")
app.add_typer(tokens_app, name="tokens")
register_addon_commands(app)


# Suppress warnings from litellm, see https://github.com/BerriAI/litellm/issues/11759
warnings.filterwarnings("ignore", category=UserWarning)


# Workaround for `no_args_is_help` not working, keep this until #1240 in typer is fixed
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        raise typer.Exit()


@app.command()
def init(
    model: Annotated[
        str,
        typer.Option(
            ...,
            "--model",
            "-m",
            help="The model to use for the session.",
        ),
    ] = "openrouter/google/gemini-2.5-pro",
) -> None:
    """
    Initializes a new AI session in the current directory.
    """
    session_file = Path.cwd() / SESSION_FILE_NAME
    if session_file.exists():
        print(
            f"Error: Session file '{session_file}' already exists in this directory.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    new_session = SessionData(model=model, chat_history=[], context_files=[])
    save_session(session_file, new_session)

    print(f"Initialized session file: {session_file}")


def _render_content(content: str, use_rich_markdown: bool) -> None:
    """Helper to render content to the console."""
    if use_rich_markdown:
        console = Console()
        console.print(Markdown(content))
    else:
        # Use an empty end='' to prevent adding an extra newline if the content
        # already has one, which is common for diffs.
        print(content, end="")


@app.command()
def last(
    verbatim: Annotated[
        bool,
        typer.Option(
            "--verbatim",
            help="Show the verbatim response from the AI with no processing.",
        ),
    ] = False,
    recompute: Annotated[
        bool,
        typer.Option(
            "--recompute",
            "-r",
            help="Recalculate the response against the current state of files.",
        ),
    ] = False,
) -> None:
    """
    Prints the last processed response from the AI to standard output.

    By default, it shows the response as it was originally generated.
    Use --recompute to re-apply the AI's instructions to the current file state.
    """
    session_file, session_data = load_session()
    last_resp = session_data.last_response
    if not last_resp:
        print("Error: No last response found in session.", file=sys.stderr)
        raise typer.Exit(code=1)

    if verbatim:
        if last_resp.raw_content:
            _render_content(last_resp.raw_content, is_terminal())
        return

    final_unified_diff: str | None
    final_display_content: str | None

    if recompute:
        session_root = session_file.parent
        original_file_contents = _build_original_file_contents(
            context_files=session_data.context_files, session_root=session_root
        )
        final_unified_diff = generate_unified_diff(original_file_contents, last_resp.raw_content)
        final_display_content = generate_display_content(original_file_contents, last_resp.raw_content)
    else:
        # Use stored data
        final_unified_diff = last_resp.unified_diff
        final_display_content = last_resp.display_content or last_resp.raw_content

    content_to_show: str | None = None
    use_rich_markdown = False

    if is_terminal():
        content_to_show = final_display_content
        use_rich_markdown = True
    else:
        content_to_show = final_unified_diff or final_display_content

    if content_to_show:
        _render_content(content_to_show, use_rich_markdown)


@app.command()
def add(file_paths: list[Path]) -> None:
    """
    Adds one or more files to the context for the AI session.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent

    files_were_added = False
    errors_found = False

    for file_path in file_paths:
        if not file_path.is_file():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            errors_found = True
            continue

        relative_path_str = get_relative_path_or_error(file_path, session_root)

        if not relative_path_str:
            errors_found = True
            continue

        if relative_path_str not in session_data.context_files:
            session_data.context_files.append(relative_path_str)
            files_were_added = True
            print(f"Added file to context: {relative_path_str}")
        else:
            print(f"File already in context: {relative_path_str}")

    if files_were_added:
        session_data.context_files.sort()
        save_session(session_file, session_data)

    if errors_found:
        raise typer.Exit(code=1)


@app.command()
def drop(
    file_paths: Annotated[
        list[Path],
        typer.Argument(autocompletion=complete_files_in_context),
    ],
) -> None:
    """
    Drops one or more files from the context for the AI session.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent

    files_were_dropped = False
    errors_found = False

    new_context_files = session_data.context_files[:]

    for file_path in file_paths:
        relative_path_str = get_relative_path_or_error(file_path, session_root)

        if not relative_path_str:
            errors_found = True
            continue

        if relative_path_str in new_context_files:
            new_context_files.remove(relative_path_str)
            files_were_dropped = True
            print(f"Dropped file from context: {relative_path_str}")
        else:
            print(f"Error: File not in context: {file_path}", file=sys.stderr)
            errors_found = True

    if files_were_dropped:
        session_data.context_files = sorted(new_context_files)
        save_session(session_file, session_data)

    if errors_found:
        raise typer.Exit(code=1)


def _build_token_usage(usage: LiteLLMUsage) -> TokenUsage | None:
    """
    Converts a litellm usage object to our TokenUsage model.
    """
    return TokenUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _process_chunk(chunk: object) -> tuple[str | None, TokenUsage | None]:
    token_usage: TokenUsage | None = None
    if (usage := getattr(chunk, "usage", None)) and isinstance(usage, LiteLLMUsage):
        token_usage = _build_token_usage(usage)
    if isinstance(chunk, LiteLLMChoiceContainer) and chunk.choices and (delta := chunk.choices[0].delta.content):
        return delta, token_usage
    return None, token_usage


def _handle_unified_streaming(
    model_name: str,
    chat_history: list[ChatMessageHistoryItem],
    original_file_contents: FileContents,
    messages: list[LLMChatMessage],
) -> tuple[str, str | None, TokenUsage | None, float | None]:
    """
    Handles the streaming logic for all modes, always attempting to parse
    and render diffs live.
    """
    import litellm

    full_llm_response_buffer: str = ""
    token_usage: TokenUsage | None = None

    stream = litellm.completion(  # pyright: ignore[reportUnknownMemberType]
        model=model_name,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )

    if is_terminal():
        with Live(console=Console(), auto_refresh=False) as live:
            for chunk in stream:
                delta, token_usage = _process_chunk(chunk)
                if delta:
                    full_llm_response_buffer += delta
                    display_content = generate_display_content(original_file_contents, full_llm_response_buffer)
                    live.update(Markdown(display_content), refresh=True)
    else:
        for chunk in stream:
            delta, token_usage = _process_chunk(chunk)
            if delta:
                full_llm_response_buffer += delta

    if (usage := getattr(stream, "usage", None)) and not token_usage and isinstance(usage, LiteLLMUsage):
        token_usage = _build_token_usage(usage)

    final_display_content = generate_display_content(original_file_contents, full_llm_response_buffer)

    message_cost: float | None = None
    if token_usage:
        message_cost = calculate_and_display_cost(token_usage, model_name, chat_history)

    return full_llm_response_buffer, final_display_content, token_usage, message_cost


def _build_messages(
    session_data: SessionData,
    system_prompt: str,
    prompt_text: str | None,
    piped_content: str | None,
    mode: Mode,
    original_file_contents: FileContents,
) -> list[LLMChatMessage]:
    if mode == Mode.DIFF:
        system_prompt += DIFF_MODE_INSTRUCTIONS

    context_str = "<context>\n"
    for relative_path_str, content in original_file_contents.items():
        context_str += f'  <file path="{relative_path_str}">\n{content}\n</file>\n'
    context_str += "</context>\n"

    user_prompt_parts = [context_str]
    if piped_content and prompt_text:
        # Scenario A: piped content is subject, argument is instruction
        user_prompt_parts.append(f"<stdin_content>\n{piped_content}\n</stdin_content>\n")
        user_prompt_parts.append(f"<prompt>\n{prompt_text}\n</prompt>")
    elif piped_content:
        # Scenario B: piped content is the prompt
        user_prompt_parts.append(f"<prompt>\n{piped_content}\n</prompt>")
    elif prompt_text:
        # Scenario C: argument is the prompt
        user_prompt_parts.append(f"<prompt>\n{prompt_text}\n</prompt>")
    user_prompt_xml = "".join(user_prompt_parts)

    messages: list[LLMChatMessage] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    active_history = session_data.chat_history[session_data.history_start_index :]
    messages.extend(reconstruct_historical_messages(active_history))

    if mode in ALIGNMENT_PROMPTS:
        messages.extend([{"role": msg.role, "content": msg.content} for msg in ALIGNMENT_PROMPTS[mode]])

    messages.append({"role": "user", "content": user_prompt_xml})

    return messages


def _build_original_file_contents(context_files: list[str], session_root: Path) -> FileContents:
    original_file_contents: FileContents = {
        relative_path_str: abs_path.read_text()
        for relative_path_str in context_files
        if (abs_path := session_root / relative_path_str).exists()
    }

    missing_files = original_file_contents.keys() - set(context_files)
    for relative_path_str in missing_files:
        print(
            f"Warning: Context file not found, skipping: {relative_path_str}",
            file=sys.stderr,
        )

    return original_file_contents


@app.command()
def prompt(
    prompt_text: Annotated[str | None, typer.Argument()] = None,
    system_prompt: Annotated[
        str, typer.Option(help="The system prompt to guide the AI.")
    ] = "You are an expert pair programmer.",
    mode: Annotated[
        Mode,
        typer.Option(
            help="Output mode: 'diff' for git diffs, 'conversation' for discussion (default)"
            + ", or 'raw' for no prompt additions.",
            case_sensitive=False,
        ),
    ] = Mode.CONVERSATION,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Sends a prompt to the AI with the current context.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent
    timestamp = datetime.now(UTC).isoformat()
    model_name = model or session_data.model  # The model argument is an override for the session's model

    piped_content: str | None = None
    if not is_input_terminal():
        content = sys.stdin.read()
        if content:
            piped_content = content

    # Validate that we have some form of prompt
    final_content: str
    final_piped_content: str | None = None
    match (piped_content, prompt_text):
        case (str(), str()):
            final_content = prompt_text
            final_piped_content = piped_content
        case (str(), None):
            final_content = piped_content
        case (None, str()):
            final_content = prompt_text
        case _:
            prompt_text = Prompt.ask("Prompt")
            if not prompt_text.strip():
                print("Error: Prompt is required.", file=sys.stderr)
                raise typer.Exit(code=1)
            final_content = prompt_text

    original_file_contents = _build_original_file_contents(
        context_files=session_data.context_files, session_root=session_root
    )

    messages = _build_messages(
        session_data,
        system_prompt,
        prompt_text=prompt_text,
        piped_content=piped_content,
        mode=mode,
        original_file_contents=original_file_contents,
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
        ) = _handle_unified_streaming(model_name, session_data.chat_history, original_file_contents, messages)
        duration_ms = int((time.monotonic() - start_time) * 1000)
    except Exception as e:
        # Specific error handling can be improved in handlers if needed
        print(f"Error calling LLM API: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from e

    # 6. Process Output for Storage and Non-TTY
    # The `display_content` is already generated by the streaming handler.
    # We only need to generate the `unified_diff` for saving and non-TTY output.
    unified_diff = generate_unified_diff(original_file_contents, llm_response_content)

    # 7. Update State & Save
    assistant_response_timestamp = datetime.now(UTC).isoformat()

    # Determine what to save in history based on inputs

    session_data.chat_history.append(
        UserChatMessage(
            role="user",
            content=final_content,
            piped_content=final_piped_content,
            mode=mode,
            timestamp=timestamp,
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
        )
    )

    session_data.last_response = LastResponse(
        raw_content=llm_response_content,
        mode_used=mode,
        unified_diff=unified_diff,
        display_content=display_content,
        token_usage=token_usage,
        cost=message_cost,
        model=model_name,
        timestamp=assistant_response_timestamp,
        duration_ms=duration_ms,
    )

    save_session(session_file, session_data)

    # 8. Print Final Output
    # This phase handles non-interactive output. All interactive output is handled
    # by the streaming functions.
    if not is_terminal():
        match mode:
            case Mode.DIFF:
                if unified_diff:
                    print(unified_diff, end="")
            case Mode.CONVERSATION | Mode.RAW:
                # For these modes, the handler is silent in non-TTY, so we print the final result.
                print(llm_response_content)


if __name__ == "__main__":
    app()
