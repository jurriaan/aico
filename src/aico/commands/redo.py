from typing import Annotated

import typer

from aico.index_logic import load_session_and_resolve_indices
from aico.lib.session import save_session


def redo(
    index: Annotated[str, typer.Argument(help="Index of the message pair to redo (e.g., -1 for last).")] = "-1",
) -> None:
    """
    Re-include a message pair in context.
    """
    session_file, session_data, pair_indices, resolved_index = load_session_and_resolve_indices(index)

    user_message = session_data.chat_history[pair_indices.user_index]
    assistant_message = session_data.chat_history[pair_indices.assistant_index]

    if not user_message.is_excluded or not assistant_message.is_excluded:
        print(f"Pair at index {resolved_index} is already active. No changes made.")
        raise typer.Exit(code=0)

    from dataclasses import replace

    session_data.chat_history[pair_indices.user_index] = replace(user_message, is_excluded=False)
    session_data.chat_history[pair_indices.assistant_index] = replace(assistant_message, is_excluded=False)

    save_session(session_file, session_data)

    print(f"Re-included pair at index {resolved_index} in context.")
