from typing import Annotated

import typer

from aico.core.session_context import is_pair_excluded, set_pair_excluded
from aico.core.session_loader import load_session_and_resolve_indices


def redo(
    index: Annotated[str, typer.Argument(help="Index of the message pair to redo (e.g., -1 for last).")] = "-1",
) -> None:
    """
    Re-include a message pair in context.
    """
    session, _pair_indices, resolved_index = load_session_and_resolve_indices(index)

    if not is_pair_excluded(session.data, resolved_index):
        print(f"Pair at index {resolved_index} is already active. No changes made.")
        raise typer.Exit(code=0)

    _ = set_pair_excluded(session.data, resolved_index, False)

    session.persistence.update_view_metadata(excluded_pairs=session.data.excluded_pairs)

    print(f"Re-included pair at index {resolved_index} in context.")
