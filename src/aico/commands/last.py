import sys

import typer
from rich.console import Console

from aico.core.session_loader import load_session_and_resolve_indices
from aico.lib.diffing import recompute_derived_content
from aico.lib.models import AssistantChatMessage, DisplayItem
from aico.lib.ui import (
    is_terminal,
    reconstruct_display_content_for_piping,
    render_display_items_to_rich,
)


def _render_content(content: str, use_rich_markdown: bool) -> None:
    """Helper to render content to the console."""
    if use_rich_markdown:
        console = Console()
        from rich.markdown import Markdown

        console.print(Markdown(content))
    else:
        # Use an empty end='' to prevent adding an extra newline if the content
        # already has one, which is common for diffs.
        print(content, end="")


def last(
    index: str,
    prompt: bool,
    verbatim: bool,
    recompute: bool,
) -> None:
    from rich.markdown import Markdown

    session, pair_indices, _ = load_session_and_resolve_indices(index)

    if prompt:
        if recompute:
            print("Error: --recompute cannot be used with --prompt.", file=sys.stderr)
            raise typer.Exit(code=1)

        target_user_msg = session.data.chat_history[pair_indices.user_index]
        if target_user_msg.content:
            _render_content(target_user_msg.content, is_terminal() and not verbatim)
        return

    # --- Start of Assistant Message Handling ---
    target_msg = session.data.chat_history[pair_indices.assistant_index]
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
    derived_obj = None

    if recompute:
        derived_obj = recompute_derived_content(
            assistant_content=target_msg.content,
            context_files=session.data.context_files,
            session_root=session.root,
        )
    else:
        derived_obj = target_msg.derived

    if derived_obj:
        unified_diff = derived_obj.unified_diff
        display_content = derived_obj.display_content or target_msg.content
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
