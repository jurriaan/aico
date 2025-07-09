import sys
from dataclasses import replace
from typing import Annotated

import typer

from aico.index_logic import resolve_pair_index_to_message_indices
from aico.utils import load_session, save_session


def undo(
    index: Annotated[
        str,
        typer.Argument(
            help="The index of the message pair to undo. Use negative numbers to count from the end "
            + "(e.g., -1 for the last pair).",
        ),
    ] = "-1",
) -> None:
    """
    Mark a message pair as excluded from future context.

    This command performs a "soft delete" on the pair at the given INDEX.
    The messages are not removed from the history, but are flagged to be
    ignored when building the context for the next prompt.
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

    user_msg_idx = pair_indices.user_index
    assistant_msg_idx = pair_indices.assistant_index

    user_msg = session_data.chat_history[user_msg_idx]
    assistant_msg = session_data.chat_history[assistant_msg_idx]

    if user_msg.is_excluded and assistant_msg.is_excluded:
        print(f"Pair at index {index_val} is already excluded. No changes made.")
        return

    session_data.chat_history[user_msg_idx] = replace(user_msg, is_excluded=True)
    session_data.chat_history[assistant_msg_idx] = replace(assistant_msg, is_excluded=True)

    save_session(session_file, session_data)
    print(f"Marked pair at index {index_val} as excluded.")
