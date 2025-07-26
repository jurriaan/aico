import sys
from dataclasses import replace
from typing import Annotated

import typer

from aico.index_logic import find_message_pairs, resolve_pair_index_to_message_indices
from aico.lib.session import load_session, save_session


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
    Exclude a message pair from the context [default: last].

    This command performs a "soft delete" on the pair at the given INDEX.
    The messages are not removed from the history, but are flagged to be
    ignored when building the context for the next prompt.
    """
    session_file, session_data = load_session()
    all_pairs = find_message_pairs(session_data.chat_history)

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

    resolved_index = index_val
    if resolved_index < 0:
        # This is safe because resolve_pair_index_to_message_indices has already validated the index
        resolved_index += len(all_pairs)

    if user_msg.is_excluded and assistant_msg.is_excluded:
        print(f"Pair at index {resolved_index} is already excluded. No changes made.")
        return

    session_data.chat_history[user_msg_idx] = replace(user_msg, is_excluded=True)
    session_data.chat_history[assistant_msg_idx] = replace(assistant_msg, is_excluded=True)

    save_session(session_file, session_data)
    print(f"Marked pair at index {resolved_index} as excluded.")
