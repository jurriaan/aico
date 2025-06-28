import sys
import warnings
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from aico.addons import register_addon_commands
from aico.commands.prompt import prompt
from aico.diffing import (
    generate_display_content,
    generate_unified_diff,
)
from aico.history import history_app
from aico.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    SessionData,
)
from aico.tokens import tokens_app
from aico.utils import (
    SESSION_FILE_NAME,
    build_original_file_contents,
    complete_files_in_context,
    get_relative_path_or_error,
    is_terminal,
    load_session,
    save_session,
)

app = typer.Typer()
app.add_typer(history_app, name="history")
app.add_typer(tokens_app, name="tokens")
_ = app.command("prompt")(prompt)
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


def _find_nth_last_assistant_message(history: list[ChatMessageHistoryItem], n: int) -> AssistantChatMessage | None:
    """
    Finds the Nth-to-last assistant message in the chat history.
    n=1 is the most recent, n=2 is the second most recent, etc.
    """
    if n < 1:
        return None

    count = 0
    for msg in reversed(history):
        if isinstance(msg, AssistantChatMessage):
            count += 1
            if count == n:
                return msg
    return None


@app.command()
def last(
    n: Annotated[
        int,
        typer.Argument(
            help="The Nth-to-last assistant response to show (e.g., 1 for the last, 2 for the second-to-last).",
            min=1,
        ),
    ] = 1,
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
    Prints a processed response from the AI to standard output.

    By default, it shows the last response as it was originally generated.
    Use N to select a specific historical response.
    Use --recompute to re-apply the AI's instructions to the current file state.
    """
    session_file, session_data = load_session()
    target_asst_msg = _find_nth_last_assistant_message(session_data.chat_history, n)
    if not target_asst_msg:
        print(f"Error: Assistant response at index {n} not found.", file=sys.stderr)
        raise typer.Exit(code=1)

    if verbatim:
        if target_asst_msg.content:
            _render_content(target_asst_msg.content, is_terminal())
        return

    final_unified_diff: str | None = None
    final_display_content: str | None = None

    if recompute:
        session_root = session_file.parent
        original_file_contents = build_original_file_contents(
            context_files=session_data.context_files, session_root=session_root
        )
        final_unified_diff = generate_unified_diff(original_file_contents, target_asst_msg.content, session_root)
        final_display_content = generate_display_content(original_file_contents, target_asst_msg.content, session_root)
    else:
        # Use stored data
        if target_asst_msg.derived:
            final_unified_diff = target_asst_msg.derived.unified_diff
            # Fallback to raw content if display_content was optimized away
            final_display_content = target_asst_msg.derived.display_content or target_asst_msg.content
        else:
            # Purely conversational messages have no derived content
            final_display_content = target_asst_msg.content

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


if __name__ == "__main__":
    app()
