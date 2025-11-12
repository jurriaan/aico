from typing import Annotated

import typer

from aico.core.session_persistence import get_persistence
from aico.historystore import SessionView, save_view, switch_active_pointer
from aico.historystore.pointer import load_pointer


def session_new(
    name: Annotated[str, typer.Argument(help="Name for the new, empty session view (branch).")],
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="The model to use for the new session. If omitted, inherits from the current session.",
        ),
    ] = None,
) -> None:
    """
    Create a new, empty session view (branch) and switch to it.
    """
    if not name.strip():
        typer.echo("Error: New session name is required.", err=True)
        raise typer.Exit(code=1)

    persistence = get_persistence()
    session_file, session_data = persistence.load()

    # Validate we are in a shared-history project by trying to load the pointer
    # This also gives us the absolute path to the active view, which we don't need, but it's a good check.
    active_view_path = load_pointer(session_file)

    sessions_dir = active_view_path.parent
    new_view_path = sessions_dir / f"{name}.json"

    if new_view_path.exists():
        typer.echo(f"Error: A session view named '{name}' already exists.", err=True)
        raise typer.Exit(code=1)

    new_model = model or session_data.model

    view = SessionView(model=new_model, context_files=[], message_indices=[], history_start_pair=0, excluded_pairs=[])
    save_view(new_view_path, view)
    switch_active_pointer(session_file, new_view_path)

    typer.echo(f"Created new empty session '{name}' with model '{new_model}' and switched to it.")
