from typing import Annotated

import typer

from aico.core.session_persistence import get_persistence
from aico.historystore import switch_active_pointer
from aico.historystore.pointer import load_pointer


def session_switch(
    name: Annotated[str, typer.Argument(help="Name of the session view (branch) to activate.")],
) -> None:
    """
    Switch the active session pointer to another existing view (branch).
    """
    persistence = get_persistence(require_type="shared")
    session_file, _ = persistence.load()

    # Validate pointer and resolve current active view (ensures shared-history)
    _ = load_pointer(session_file)

    sessions_dir = session_file.parent / ".aico" / "sessions"
    if not sessions_dir.is_dir():
        typer.echo("Error: Sessions directory '.aico/sessions' not found.", err=True)
        raise typer.Exit(code=1)

    target_view_path = sessions_dir / f"{name}.json"
    if not target_view_path.is_file():
        typer.echo(f"Error: Session view '{name}' not found at {target_view_path}.", err=True)
        raise typer.Exit(code=1)

    switch_active_pointer(session_file, target_view_path)
    print(f"Switched active session to: {name}")
