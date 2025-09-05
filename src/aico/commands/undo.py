from typing import Annotated

import typer

from aico.index_logic import is_pair_excluded, load_session_and_resolve_indices, set_pair_excluded
from aico.lib.session import save_session


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
    session_file, session_data, pair_indices, resolved_index = load_session_and_resolve_indices(index)

    if is_pair_excluded(session_data, pair_indices):
        print(f"Pair at index {resolved_index} is already excluded. No changes made.")
        return

    _ = set_pair_excluded(session_data, pair_indices, True)

    save_session(session_file, session_data)
    print(f"Marked pair at index {resolved_index} as excluded.")
