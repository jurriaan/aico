import json

from pydantic import TypeAdapter
from rich.console import Console

from aico.console import (
    is_terminal,
    reconstruct_display_content_for_piping,
    render_display_items_to_rich,
)
from aico.diffing.stream_processor import recompute_derived_content
from aico.exceptions import AicoError, InvalidInputError
from aico.historystore import load_view
from aico.models import AssistantChatMessage, DisplayItem, UserChatMessage
from aico.session_loader import load_session_and_resolve_indices
from aico.session_persistence import SharedHistoryPersistence


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
    json_output: bool,
) -> None:
    from rich.markdown import Markdown

    session, pair_indices, resolved_pair_index = load_session_and_resolve_indices(index)

    if json_output:
        user_msg = session.data.chat_history[pair_indices.user_index]
        asst_msg = session.data.chat_history[pair_indices.assistant_index]

        user_id: int | None = None
        assistant_id: int | None = None

        if isinstance(session.persistence, SharedHistoryPersistence):
            view = load_view(session.persistence.view_path)
            # When full history is loaded, resolved_pair_index is already absolute (0-based from start of session).
            # We do NOT add history_start_pair.
            user_msg_idx = resolved_pair_index * 2
            asst_msg_idx = resolved_pair_index * 2 + 1

            if asst_msg_idx < len(view.message_indices):
                user_id = view.message_indices[user_msg_idx]
                assistant_id = view.message_indices[asst_msg_idx]

        assert isinstance(user_msg, UserChatMessage)
        user_dict = TypeAdapter(UserChatMessage).dump_python(user_msg, mode="json")  # pyright: ignore[reportAny]
        user_dict["id"] = user_id

        assert isinstance(asst_msg, AssistantChatMessage)
        asst_dict = TypeAdapter(AssistantChatMessage).dump_python(asst_msg, mode="json")  # pyright: ignore[reportAny]
        asst_dict["id"] = assistant_id

        output = {
            "pair_index": resolved_pair_index,
            "user": user_dict,
            "assistant": asst_dict,
        }
        print(json.dumps(output))
        return

    if prompt:
        if recompute:
            raise InvalidInputError("--recompute cannot be used with --prompt.")

        target_user_msg = session.data.chat_history[pair_indices.user_index]

        if target_user_msg.content:
            _render_content(target_user_msg.content, is_terminal() and not verbatim)
        return

    # --- Start of Assistant Message Handling ---
    target_msg = session.data.chat_history[pair_indices.assistant_index]
    if not isinstance(target_msg, AssistantChatMessage):
        # This is a safeguard; find_message_pairs should prevent this.
        raise AicoError("Internal error. Could not find a valid assistant message for this pair.")

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
