import typer

from aico.session import modify_pair_exclusions


def undo(
    indices: list[str] | None,
) -> None:
    # Use standard resolution logic to perform the metadata update
    actually_changed = modify_pair_exclusions(raw_indices=indices, exclude=True)

    if not actually_changed:
        print("No changes made (specified pairs were already excluded).")
        raise typer.Exit(code=0)

    if len(actually_changed) == 1:
        print(f"Marked pair at index {actually_changed[0]} as excluded.")
    else:
        changed_str = ", ".join(map(str, sorted(actually_changed)))
        print(f"Marked {len(actually_changed)} pairs as excluded: {changed_str}.")
