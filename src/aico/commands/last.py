import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from aico.diffing import (
    generate_display_content,
    generate_unified_diff,
)
from aico.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
)
from aico.utils import (
    build_original_file_contents,
    is_terminal,
    load_session,
)


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
