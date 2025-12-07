import typer

from aico.core.session_loader import load_active_session
from aico.historystore import switch_active_pointer
from aico.historystore.pointer import load_pointer


def session_switch(
    name: str,
) -> None:
    session = load_active_session()

    # Validate pointer and resolve current active view (ensures shared-history)
    _ = load_pointer(session.file_path)

    sessions_dir = session.root / ".aico" / "sessions"
    if not sessions_dir.is_dir():
        typer.echo("Error: Sessions directory '.aico/sessions' not found.", err=True)
        raise typer.Exit(code=1)

    target_view_path = sessions_dir / f"{name}.json"
    if not target_view_path.is_file():
        typer.echo(f"Error: Session view '{name}' not found at {target_view_path}.", err=True)
        raise typer.Exit(code=1)

    switch_active_pointer(session.file_path, target_view_path)
    print(f"Switched active session to: {name}")
