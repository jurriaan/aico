from typing import Annotated

import typer

from aico.index_logic import find_message_pairs, resolve_history_start_index
from aico.lib.session import load_session, save_session


def set_history(
    pair_index_str: Annotated[
        str,
        typer.Argument(
            ...,
            help="The pair index to set as the start of the active context. "
            + "Use 0 to make the full history active. "
            + "Use negative numbers to count from the end. "
            + "Use the total number of pairs to clear the context.",
        ),
    ],
) -> None:
    """
    Set the active window of the conversation history.

    Use `aico log` to see available pair indices.

    - `aico set-history 0` makes the full history active.
    - `aico set-history <num_pairs>` clears the context for the next prompt.
    """
    session_file, session_data = load_session()
    chat_history = session_data.chat_history

    target_message_index, resolved_index = resolve_history_start_index(chat_history, pair_index_str)

    session_data.history_start_index = target_message_index
    save_session(session_file, session_data)

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
