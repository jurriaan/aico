import sys
from typing import Annotated

import typer

from aico.index_logic import resolve_pair_index_to_message_indices
from aico.lib.session import load_session, save_session


def redo(
    index: Annotated[str, typer.Argument(help="Index of the message pair to redo (e.g., -1 for last).")] = "-1",
) -> None:
    """
    Re-include a message pair in context.
    """
    session_file, session_data = load_session()

    try:
        pair_index_int = int(index)
    except ValueError:
        print(f"Error: Invalid index '{index}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    try:
        pair = resolve_pair_index_to_message_indices(session_data.chat_history, pair_index_int)
    except IndexError as e:
        print(str(e), file=sys.stderr)
        raise typer.Exit(code=1) from e

    user_message = session_data.chat_history[pair.user_index]
    assistant_message = session_data.chat_history[pair.assistant_index]

    # This is safe because resolve_pair_index_to_message_indices has already validated the index
    if pair_index_int < 0:
        from aico.index_logic import find_message_pairs

        pair_index_int += len(find_message_pairs(session_data.chat_history))

    if not user_message.is_excluded or not assistant_message.is_excluded:
        print(f"Pair at index {pair_index_int} is already active. No changes made.")
        raise typer.Exit(code=0)

    from dataclasses import replace

    session_data.chat_history[pair.user_index] = replace(user_message, is_excluded=False)
    session_data.chat_history[pair.assistant_index] = replace(assistant_message, is_excluded=False)

    save_session(session_file, session_data)

    print(f"Re-included pair at index {pair_index_int} in context.")
