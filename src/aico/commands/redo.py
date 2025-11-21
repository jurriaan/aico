from typing import Annotated

import typer

from aico.core.session_loader import load_active_session, resolve_pair_index


def redo(
    indices: Annotated[
        list[str] | None,
        typer.Argument(
            help="Indices of the message pairs to redo. Use negative numbers to count from the end "
            + "(e.g., -1 for the last pair). Defaults to -1 (last).",
        ),
    ] = None,
) -> None:
    """
    Re-include one or more message pairs in context.
    """
    if not indices:
        indices = ["-1"]

    session = load_active_session(full_history=True)

    resolved_indices: list[int] = []
    for idx_str in indices:
        resolved_indices.append(resolve_pair_index(session, idx_str))

    current_excluded = set(session.data.excluded_pairs)
    actually_changed: list[int] = []

    for idx in resolved_indices:
        if idx in current_excluded:
            current_excluded.discard(idx)
            actually_changed.append(idx)

    if not actually_changed:
        print("No changes made (specified pairs were already active).")
        raise typer.Exit(code=0)

    new_excluded = sorted(current_excluded)
    session.persistence.update_view_metadata(excluded_pairs=new_excluded)

    if len(actually_changed) == 1:
        print(f"Re-included pair at index {actually_changed[0]} in context.")
    else:
        changed_str = ", ".join(map(str, sorted(actually_changed)))
        print(f"Re-included pairs: {changed_str}")
