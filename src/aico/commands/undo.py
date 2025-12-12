import typer

from aico.session_loader import expand_index_ranges, load_active_session, resolve_pair_index


def undo(
    indices: list[str] | None,
) -> None:
    if not indices:
        indices = ["-1"]

    # 1. Expand ranges
    expanded_indices = expand_index_ranges(indices)

    # Load once
    session = load_active_session(full_history=True)

    # Resolve all first
    resolved_indices: list[int] = []
    for idx_str in expanded_indices:
        resolved_indices.append(resolve_pair_index(session, idx_str))

    # Calculate new state
    current_excluded = set(session.data.excluded_pairs)
    actually_changed: list[int] = []

    for idx in resolved_indices:
        if idx not in current_excluded:
            current_excluded.add(idx)
            actually_changed.append(idx)

    if not actually_changed:
        print("No changes made (specified pairs were already excluded).")
        raise typer.Exit(code=0)

    # Save once
    new_excluded = sorted(current_excluded)
    session.persistence.update_view_metadata(excluded_pairs=new_excluded)

    if len(actually_changed) == 1:
        print(f"Marked pair at index {actually_changed[0]} as excluded.")
    else:
        changed_str = ", ".join(map(str, sorted(actually_changed)))
        print(f"Marked {len(actually_changed)} pairs as excluded: {changed_str}.")
