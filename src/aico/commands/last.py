import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from aico.core.session_persistence import load_session_and_resolve_indices
from aico.lib.diffing import (
    generate_display_items,
    generate_unified_diff,
)
from aico.lib.models import AssistantChatMessage, DisplayItem
from aico.lib.session import build_original_file_contents
from aico.utils import (
    is_terminal,
    reconstruct_display_content_for_piping,
    render_display_items_to_rich,
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
    Output the last response or diff to stdout.

    By default, it shows the assistant response from the last pair.
    Use INDEX to select a specific pair (e.g., 0 for the first, -1 for the last).
    Use --prompt to see the user's prompt instead of the AI's response.
    Use --recompute to re-apply an AI's instructions to the current file state.
    """
    session_file, session_data, pair_indices, _ = load_session_and_resolve_indices(index)

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
        unified_diff = generate_unified_diff(original_file_contents, target_msg.content, session_root)
        display_content = generate_display_items(original_file_contents, target_msg.content, session_root)
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
        match display_content:
            case list() as items:
                renderable_group = render_display_items_to_rich(items)
                if renderable_group.renderables:
                    console.print(renderable_group)

            case str() as content_string:
                # Backward compatibility path: treat the old string as a single Markdown block
                if content_string:
                    console.print(Markdown(content_string))
    else:
        output_content = reconstruct_display_content_for_piping(display_content, target_msg.mode, unified_diff)
        print(output_content, end="")
