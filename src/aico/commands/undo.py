from typing import Annotated

import typer

from aico.core.session_context import is_pair_excluded
from aico.core.session_loader import load_session_and_resolve_indices


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
    session, _pair_indices, resolved_index = load_session_and_resolve_indices(index)

    # 1. Validate using current state
    if is_pair_excluded(session.data, resolved_index):
        print(f"Pair at index {resolved_index} is already excluded. No changes made.")
        raise typer.Exit(code=0)

    # 2. Calculate new state (pure logic)
    current_excluded = set(session.data.excluded_pairs)
    new_excluded = sorted(current_excluded | {resolved_index})

    # 3. Save
    session.persistence.update_view_metadata(excluded_pairs=new_excluded)
    print(f"Marked pair at index {resolved_index} as excluded.")
