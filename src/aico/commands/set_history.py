from typing import Annotated

import typer

from aico.core.session_context import resolve_start_pair_index
from aico.core.session_loader import load_active_session
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
    session = load_active_session(full_history=True)

    num_pairs = len(find_message_pairs(session.data.chat_history))

    # Handle the 'clear' keyword before numeric resolution
    if pair_index_str.lower() == "clear":
        pair_index_str = str(num_pairs)

    resolved_index = resolve_start_pair_index(pair_index_str, num_pairs)

    session.persistence.update_view_metadata(history_start_pair=resolved_index)

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
