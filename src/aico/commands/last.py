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
from aico.index_logic import resolve_pair_index_to_message_indices
from aico.models import AssistantChatMessage, DisplayItem, Mode
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


def last(
    index: Annotated[
        str,
        typer.Argument(
            help="The index of the message pair to show. Use negative numbers to count from the end "
            + "(e.g., -1 for the last pair).",
        ),
    ] = "-1",
    prompt: Annotated[
        bool,
        typer.Option(
            "--prompt",
            help="Show the user prompt instead of the assistant response.",
        ),
    ] = False,
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
            help="Recalculate the response against the current state of files. Only valid for assistant responses.",
        ),
    ] = False,
) -> None:
    """
    Prints a historical message to standard output.

    By default, it shows the assistant response from the last pair.
    Use INDEX to select a specific pair (e.g., 0 for the first, -1 for the last).
    Use --prompt to see the user's prompt instead of the AI's response.
    Use --recompute to re-apply an AI's instructions to the current file state.
    """
    session_file, session_data = load_session()

    try:
        index_val = int(index)
    except ValueError:
        print(f"Error: Invalid index '{index}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    try:
        pair_indices = resolve_pair_index_to_message_indices(session_data.chat_history, index_val)
    except IndexError as e:
        print(str(e), file=sys.stderr)
        raise typer.Exit(code=1) from None

    if prompt:
        if recompute:
            print("Error: --recompute cannot be used with --prompt.", file=sys.stderr)
            raise typer.Exit(code=1)

        target_user_msg = session_data.chat_history[pair_indices.user_index]
        if target_user_msg.content:
            _render_content(target_user_msg.content, is_terminal() and not verbatim)
        return

    # --- Start of Assistant Message Handling ---
    target_msg = session_data.chat_history[pair_indices.assistant_index]
    if not isinstance(target_msg, AssistantChatMessage):
        # This is a safeguard; find_message_pairs should prevent this.
        print("Error: Internal error. Could not find a valid assistant message for this pair.", file=sys.stderr)
        raise typer.Exit(code=1)

    if verbatim:
        if target_msg.content:
            _render_content(target_msg.content, is_terminal())
        return

    unified_diff: str | None = None
    display_content: str | list[DisplayItem] | None = None

    if recompute:
        session_root = session_file.parent
        original_file_contents = build_original_file_contents(
            context_files=session_data.context_files, session_root=session_root
        )
        _, _, warnings = process_patches_sequentially(original_file_contents, target_msg.content, session_root)
        unified_diff = generate_unified_diff(original_file_contents, target_msg.content, session_root)
        display_content = generate_display_items(original_file_contents, target_msg.content, session_root)

        if warnings:
            console = Console(stderr=True)
            console.print("[yellow]Warnings:[/yellow]")
            for warning in warnings:
                console.print(f"[yellow]{warning.text}[/yellow]")
    else:
        # Use stored data
        if target_msg.derived:
            unified_diff = target_msg.derived.unified_diff
            display_content = target_msg.derived.display_content or target_msg.content
        else:
            unified_diff = None
            display_content = target_msg.content

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
        if target_msg.mode == Mode.DIFF:
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
