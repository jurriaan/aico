from typing import Annotated

import typer

from aico.core.session_context import find_message_pairs, resolve_history_start_index
from aico.core.session_persistence import get_persistence


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
    _session_file, session_data = persistence.load()
    chat_history = session_data.chat_history

    # Handle the 'clear' keyword before numeric resolution
    if pair_index_str.lower() == "clear":
        num_pairs = len(find_message_pairs(chat_history))
        pair_index_str = str(num_pairs)

    target_message_index, resolved_index = resolve_history_start_index(chat_history, pair_index_str)

    session_data.history_start_index = target_message_index
    # Also set pair-centric field for canonical state
    session_data.history_start_pair = (
        resolved_index if target_message_index != len(chat_history) else len(find_message_pairs(chat_history))
    )
    persistence.update_view_metadata(history_start_pair=session_data.history_start_pair)

    # Determine the appropriate success message without re-validating input
    pairs = find_message_pairs(chat_history)
    num_pairs = len(pairs)

    if target_message_index == 0:
        if num_pairs == 0:
            print("History context is empty and active.")
        else:
            print("History context reset. Full chat history is now active.")
    elif target_message_index == len(chat_history):
        print("History context cleared (will start after the last conversation).")
    else:
        print(f"History context will now start at pair {resolved_index}.")
