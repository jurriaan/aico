import sys
import time
import warnings
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Protocol, cast, runtime_checkable

import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from aico.diffing import (
    generate_display_content,
    generate_unified_diff,
)
from aico.history import history_app
from aico.models import (
    AssistantChatMessage,
    LastResponse,
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
    find_session_file,
    get_relative_path_or_error,
    is_terminal,
    load_session,
)

app = typer.Typer()
app.add_typer(history_app, name="history")
app.add_typer(tokens_app, name="tokens")

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
    existing_session_file = find_session_file()
    if existing_session_file:
        print(
            f"Error: An existing session was found at '{existing_session_file}'. Please run commands from that directory or its subdirectories.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    session_file = Path.cwd() / SESSION_FILE_NAME
    if session_file.exists():
        print(
            f"Error: Session file '{session_file}' already exists in this directory.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    new_session = SessionData(model=model)
    _ = session_file.write_text(new_session.model_dump_json(indent=2))

    print(f"Initialized session file: {session_file}")


@app.command()
def last(
    verbatim: Annotated[
        bool,
        typer.Option(
            "--verbatim",
            help="Show the verbatim response from the AI with no processing.",
        ),
    ] = False,
) -> None:
    """
    Prints the last processed response from the AI to standard output.
    """
    _, session_data = load_session()
    last_resp = session_data.last_response
    if not last_resp:
        print("Error: No last response found in session.", file=sys.stderr)
        raise typer.Exit(code=1)

    # Determine what content to show based on the verbatim flag and TTY status
    content_to_show: str | None = None
    use_rich_markdown = False

    if verbatim:
        content_to_show = last_resp.raw_content
        use_rich_markdown = is_terminal()
    else:
        # Smart default
        if is_terminal():
            # In a TTY, prefer the pretty display_content; if it's empty (e.g. no diffs found),
            # fall back to the raw_content. This covers conversational responses.
            content_to_show = last_resp.display_content or last_resp.raw_content
            use_rich_markdown = True
        else:
            # When piped, output depends on the mode that was used.
            if last_resp.mode_used == Mode.DIFF:
                # For diff mode, output the clean unified_diff for piping to `git apply`.
                content_to_show = last_resp.unified_diff
            else:
                # For conversation/raw, output the display_content, which contains formatted
                # markdown suitable for piping to tools like `less` or for review.
                content_to_show = last_resp.display_content or last_resp.raw_content

    # Render the content
    if content_to_show:
        if use_rich_markdown:
            console = Console()
            console.print(Markdown(content_to_show))
        else:
            print(content_to_show)


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
        _ = session_file.write_text(session_data.model_dump_json(indent=2))

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
        _ = session_file.write_text(session_data.model_dump_json(indent=2))

    if errors_found:
        raise typer.Exit(code=1)


@runtime_checkable
class LiteLLMUsage(Protocol):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@runtime_checkable
class LiteLLMDelta(Protocol):
    content: str | None


@runtime_checkable
class LiteLLMStreamChoice(Protocol):
    delta: LiteLLMDelta


@runtime_checkable
class LiteLLMChoiceContainer(Protocol):
    choices: Sequence[LiteLLMStreamChoice]


def _build_token_usage(usage: LiteLLMUsage) -> TokenUsage | None:
    """
    Converts a litellm usage object to our TokenUsage model.
    """
    return TokenUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _handle_unified_streaming(
    session_data: SessionData,
    original_file_contents: dict[str, str],
    messages: list[dict[str, str]],
) -> tuple[str, str | None, TokenUsage | None, float | None]:
    """
    Handles the streaming logic for all modes, always attempting to parse
    and render diffs live.
    """
    import litellm

    full_llm_response_buffer: str
    full_llm_response_buffer = ""
    token_usage: TokenUsage | None = None

    stream = litellm.completion(  # pyright: ignore[reportUnknownMemberType]
        model=session_data.model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )

    if is_terminal():
        with Live(console=Console(), auto_refresh=False) as live:
            for chunk in stream:
                chunk = cast(object, chunk)

                if isinstance(chunk, LiteLLMChoiceContainer) and chunk.choices:
                    if delta := chunk.choices[0].delta.content:
                        full_llm_response_buffer += delta
                        display_content = generate_display_content(
                            original_file_contents, full_llm_response_buffer
                        )
                        live.update(Markdown(display_content), refresh=True)
                if usage := getattr(chunk, "usage", None):
                    if isinstance(usage, LiteLLMUsage):
                        token_usage = _build_token_usage(usage)
    else:
        for chunk in stream:
            # LiteLLM has weird typing, we treat it as a generic object and use protocols to use the data.
            chunk = cast(object, chunk)

            if isinstance(chunk, LiteLLMChoiceContainer) and chunk.choices:
                if delta := chunk.choices[0].delta.content:
                    full_llm_response_buffer += delta
                if usage := getattr(chunk, "usage", None):
                    if isinstance(usage, LiteLLMUsage):
                        token_usage = _build_token_usage(usage)

    if usage := getattr(stream, "usage", None):
        if not token_usage and isinstance(usage, LiteLLMUsage):
            token_usage = _build_token_usage(usage)

    final_display_content = generate_display_content(
        original_file_contents, full_llm_response_buffer
    )

    message_cost: float | None = None
    if token_usage:
        message_cost = calculate_and_display_cost(token_usage, session_data)

    return full_llm_response_buffer, final_display_content, token_usage, message_cost


@app.command()
def prompt(
    prompt_text: str,
    system_prompt: Annotated[
        str, typer.Option(help="The system prompt to guide the AI.")
    ] = "You are an expert pair programmer.",
    mode: Annotated[
        Mode,
        typer.Option(
            help="Output mode: 'diff' for git diffs, 'conversation' for discussion (default), or 'raw' for no prompt additions.",
            case_sensitive=False,
        ),
    ] = Mode.CONVERSATION,
) -> None:
    """
    Sends a prompt to the AI with the current context.
    """
    # 1. Load State
    session_file, session_data = load_session()
    session_root = session_file.parent
    timestamp = datetime.now(timezone.utc).isoformat()

    # 2. Prepare System Prompt
    if mode == Mode.DIFF:
        system_prompt += DIFF_MODE_INSTRUCTIONS

    # 3. Construct User Prompt
    context_str = "<context>\n"
    original_file_contents: dict[str, str] = {}
    for relative_path_str in session_data.context_files:
        try:
            # Reconstruct absolute path to read the file
            abs_path = session_root / relative_path_str
            content = abs_path.read_text()
            # Key the contents by the relative path
            original_file_contents[relative_path_str] = content
            # Send the relative path to the LLM
            context_str += f'  <file path="{relative_path_str}">\n{content}\n</file>\n'
        except FileNotFoundError:
            print(
                f"Warning: Context file not found, skipping: {relative_path_str}",
                file=sys.stderr,
            )
    context_str += "</context>\n"

    user_prompt_xml = f"{context_str}<prompt>\n{prompt_text}\n</prompt>"

    # 4. Construct Messages
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    active_history = session_data.chat_history[session_data.history_start_index :]
    messages.extend(
        [{"role": msg.role, "content": msg.content} for msg in active_history]
    )

    if mode in ALIGNMENT_PROMPTS:
        alignment_msgs = ALIGNMENT_PROMPTS[mode]
        messages.extend([msg.model_dump() for msg in alignment_msgs])

    messages.append({"role": "user", "content": user_prompt_xml})

    # 5. Call LLM (Streaming)
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
        ) = _handle_unified_streaming(session_data, original_file_contents, messages)
        duration_ms = int((time.monotonic() - start_time) * 1000)
    except Exception as e:
        # Specific error handling can be improved in handlers if needed
        print(f"Error calling LLM API: {e}", file=sys.stderr)
        raise typer.Exit(code=1)

    # 6. Process Output for Storage and Non-TTY
    # The `display_content` is already generated by the streaming handler.
    # We only need to generate the `unified_diff` for saving and non-TTY output.
    unified_diff = generate_unified_diff(original_file_contents, llm_response_content)

    # 7. Update State & Save
    assistant_response_timestamp = datetime.now(timezone.utc).isoformat()

    session_data.chat_history.append(
        UserChatMessage(
            role="user",
            content=prompt_text,
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
            model=session_data.model,
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
        model=session_data.model,
        timestamp=assistant_response_timestamp,
        duration_ms=duration_ms,
    )

    _ = session_file.write_text(session_data.model_dump_json(indent=2))

    # 8. Print Final Output
    # This phase handles non-interactive output. All interactive output is handled
    # by the streaming functions.
    if not is_terminal():
        match mode:
            case Mode.DIFF:
                if unified_diff:
                    print(unified_diff)
            case Mode.CONVERSATION | Mode.RAW:
                # For these modes, the handler is silent in non-TTY, so we print the final result.
                print(llm_response_content)


if __name__ == "__main__":
    app()
