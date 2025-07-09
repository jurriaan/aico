import sys
from typing import Annotated

import typer

from aico.index_logic import find_message_pairs
from aico.utils import load_session, save_session


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
    Sets the history start point to the beginning of a specific message pair.

    Use `aico log` to see available pair indices.

    - `aico set-history 0` makes the full history active.
    - `aico set-history <num_pairs>` clears the context for the next prompt.
    """
    session_file, session_data = load_session()
    chat_history = session_data.chat_history

    try:
        pair_index_val = int(pair_index_str)
    except ValueError:
        print(f"Error: Invalid index '{pair_index_str}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    pairs = find_message_pairs(chat_history)
    num_pairs = len(pairs)
    target_message_index: int

    if num_pairs == 0:
        if pair_index_val == 0:
            target_message_index = 0
        else:
            print("Error: No message pairs found. The only valid index is 0.", file=sys.stderr)
            raise typer.Exit(code=1)
    elif -num_pairs <= pair_index_val < num_pairs:
        # Valid positive or negative index for an existing pair
        target_message_index = pairs[pair_index_val].user_index
    elif pair_index_val == num_pairs:
        # Special case: set start index after the last pair, clearing the context
        target_message_index = len(chat_history)
    else:
        # Index is out of bounds
        if num_pairs == 1:
            err_msg = "Error: Index out of bounds. Valid index is 0 (or -1), or 1 to clear context."
        else:
            valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
            err_msg = f"Error: Index out of bounds. Valid indices are in the range {valid_range_str}, "
            err_msg += f"or {num_pairs} to clear context."
        print(err_msg, file=sys.stderr)
        raise typer.Exit(code=1)

    session_data.history_start_index = target_message_index
    save_session(session_file, session_data)

    if pair_index_val == 0:
        if num_pairs == 0:
            print("History context is empty and active.")
        else:
            print("History context reset. Full chat history is now active.")
    elif pair_index_val == num_pairs:
        print("History context cleared (will start after the last conversation).")
    else:
        print(f"History context will now start at pair {pair_index_val}.")
