import sys
from typing import Annotated

import typer
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.text import Text

from aico.diffing import (
    generate_display_items,
    generate_unified_diff,
    process_patches_sequentially,
)
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, DisplayItem, Mode
from aico.utils import build_original_file_contents, is_terminal, load_session


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

    unified_diff: str | None = None
    display_content: str | list[DisplayItem] | None = None

    if recompute:
        session_root = session_file.parent
        original_file_contents = build_original_file_contents(
            context_files=session_data.context_files, session_root=session_root
        )
        _, _, warnings = process_patches_sequentially(original_file_contents, target_asst_msg.content, session_root)
        unified_diff = generate_unified_diff(original_file_contents, target_asst_msg.content, session_root)
        display_content = generate_display_items(original_file_contents, target_asst_msg.content, session_root)

        if warnings:
            console = Console(stderr=True)
            console.print("[yellow]Warnings:[/yellow]")
            for warning in warnings:
                console.print(f"[yellow]{warning.text}[/yellow]")
    else:
        # Use stored data
        if target_asst_msg.derived:
            unified_diff = target_asst_msg.derived.unified_diff
            display_content = target_asst_msg.derived.display_content or target_asst_msg.content
        else:
            unified_diff = None
            display_content = target_asst_msg.content

    # Unified rendering logic
    if is_terminal():
        console = Console()
        renderables: list[Markdown | Text] = []
        match display_content:
            case list() as items:
                # New, structured path
                for item in items:
                    if item["type"] == "markdown":
                        renderables.append(Markdown(item["content"]))
                    else:  # "text"
                        renderables.append(Text(item["content"]))
                if renderables:
                    console.print(Group(*renderables))

            case str() as content_string:
                # Backward compatibility path: treat the old string as a single Markdown block
                if content_string:
                    console.print(Markdown(content_string))
    else:
        # Non-TTY (piped) output logic is now driven by original intent
        if target_asst_msg.mode == Mode.DIFF:
            # Strict Contract: For 'gen' commands, the contract is strict: only ever print the diff.
            # An empty string is printed if the diff is empty or None.
            print(unified_diff or "", end="")
        else:  # Mode.CONVERSATION or Mode.RAW
            # Flexible Contract: For 'ask' or 'raw' commands, be flexible. Prioritize a valid diff,
            # but fall back to the display_content for conversations or errors.
            if unified_diff:
                print(unified_diff, end="")
            elif display_content:
                if isinstance(display_content, list):
                    # New format: reconstruct the string from display items
                    full_content = "".join(item["content"] for item in display_content)
                    print(full_content, end="")
                else:
                    # Old format: print the string directly
                    print(display_content, end="")
