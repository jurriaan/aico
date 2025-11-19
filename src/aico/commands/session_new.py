from typing import Annotated

import typer

from aico.core.session_loader import load_active_session
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

    session = load_active_session(require_type="shared")

    # We are guaranteed to be in a shared-history project; resolve active view path.
    active_view_path = load_pointer(session.file_path)

    sessions_dir = active_view_path.parent
    new_view_path = sessions_dir / f"{name}.json"

    if new_view_path.exists():
        typer.echo(f"Error: A session view named '{name}' already exists.", err=True)
        raise typer.Exit(code=1)

    new_model = model or session.data.model

    view = SessionView(model=new_model, context_files=[], message_indices=[], history_start_pair=0, excluded_pairs=[])
    save_view(new_view_path, view)
    switch_active_pointer(session.file_path, new_view_path)

    typer.echo(f"Created new empty session '{name}' with model '{new_model}' and switched to it.")
