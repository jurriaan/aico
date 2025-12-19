import typer

from aico.session import modify_pair_exclusions


def redo(
    indices: list[str] | None,
) -> None:
    # Use standard resolution logic to perform the metadata update
    actually_changed = modify_pair_exclusions(raw_indices=indices, exclude=False)

    if not actually_changed:
        print("No changes made (specified pairs were already active).")
        raise typer.Exit(code=0)

    if len(actually_changed) == 1:
        print(f"Re-included pair at index {actually_changed[0]} in context.")
    else:
        changed_str = ", ".join(map(str, sorted(actually_changed)))
        print(f"Re-included {len(actually_changed)} pairs: {changed_str}.")
