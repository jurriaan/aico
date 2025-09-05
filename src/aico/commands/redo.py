from typing import Annotated

import typer

from aico.index_logic import is_pair_excluded, load_session_and_resolve_indices, set_pair_excluded
from aico.lib.session import save_session


def redo(
    index: Annotated[str, typer.Argument(help="Index of the message pair to redo (e.g., -1 for last).")] = "-1",
) -> None:
    """
    Re-include a message pair in context.
    """
    session_file, session_data, pair_indices, resolved_index = load_session_and_resolve_indices(index)

    if not is_pair_excluded(session_data, pair_indices):
        print(f"Pair at index {resolved_index} is already active. No changes made.")
        raise typer.Exit(code=0)

    _ = set_pair_excluded(session_data, pair_indices, False)

    save_session(session_file, session_data)

    print(f"Re-included pair at index {resolved_index} in context.")
