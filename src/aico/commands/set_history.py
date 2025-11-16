from typing import Annotated

import typer

from aico.core.session_context import resolve_start_pair_index
from aico.core.session_persistence import SharedHistoryPersistence, get_persistence
from aico.lib.history_utils import find_message_pairs


def set_history(
    pair_index_str: Annotated[
        str,
        typer.Argument(
            ...,
            help="The pair index to set as the start of the active context. "
            + "Use 0 to make the full history active. "
            + "Use negative numbers to count from the end. "
            + "Use the 'clear' to clear the context.",
        ),
    ],
) -> None:
    """
    Set the active window of the conversation history.

    Use `aico log` to see available pair indices.

    - `aico set-history 0` makes the full history active.
    - `aico set-history clear` clears the context for the next prompt.
    """
    persistence = get_persistence()

    # For shared-history sessions, compute pair counts against the full history to ensure
    # accurate bounds and error messages. For legacy sessions, `load()` already returns
    # the full history.
    if isinstance(persistence, SharedHistoryPersistence):
        _session_file, session_data_full = persistence.load_full_history()
        chat_history = session_data_full.chat_history
    else:
        _session_file, session_data = persistence.load()
        chat_history = session_data.chat_history

    num_pairs = len(find_message_pairs(chat_history))

    # Handle the 'clear' keyword before numeric resolution
    if pair_index_str.lower() == "clear":
        pair_index_str = str(num_pairs)

    resolved_index = resolve_start_pair_index(pair_index_str, num_pairs)

    persistence.update_view_metadata(history_start_pair=resolved_index)

    # Determine the appropriate success message without re-validating input
    if resolved_index == 0:
        if num_pairs == 0:
            print("History context is empty and active.")
        else:
            print("History context reset. Full chat history is now active.")
    elif resolved_index == num_pairs:
        print("History context cleared (will start after the last conversation).")
    else:
        print(f"History context will now start at pair {resolved_index}.")
