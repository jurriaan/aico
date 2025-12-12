import typer

from aico.session_loader import expand_index_ranges, load_active_session, resolve_pair_index


def redo(
    indices: list[str] | None,
) -> None:
    if not indices:
        indices = ["-1"]

    # 1. Expand ranges
    expanded_indices = expand_index_ranges(indices)

    session = load_active_session(full_history=True)

    resolved_indices: list[int] = []
    for idx_str in expanded_indices:
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
        print(f"Re-included {len(actually_changed)} pairs: {changed_str}.")
