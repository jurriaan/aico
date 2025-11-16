from typing import Annotated

import typer

from aico.core.session_context import is_pair_excluded, set_pair_excluded
from aico.core.session_persistence import get_persistence, load_session_and_resolve_indices


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
    persistence = get_persistence()
    _session_file, session_data, _pair_indices, resolved_index = load_session_and_resolve_indices(
        index, persistence=persistence
    )

    if is_pair_excluded(session_data, resolved_index):
        print(f"Pair at index {resolved_index} is already excluded. No changes made.")
        raise typer.Exit(code=0)

    _ = set_pair_excluded(session_data, resolved_index, True)

    persistence.update_view_metadata(excluded_pairs=session_data.excluded_pairs)
    print(f"Marked pair at index {resolved_index} as excluded.")
