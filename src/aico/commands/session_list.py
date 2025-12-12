from pathlib import Path

import typer

from aico.session import Session


def session_list() -> None:
    session = Session.load_active()

    # Valid properties
    active_view_path = session.view_path
    sessions_dir = session.root / ".aico" / "sessions"
    if not sessions_dir.is_dir():
        typer.echo("Error: Sessions directory '.aico/sessions' not found.", err=True)
        raise typer.Exit(code=1)

    active_name = Path(active_view_path).stem

    view_files = sorted(p for p in sessions_dir.glob("*.json") if p.is_file())
    if not view_files:
        print("No session views found.")
        return

    print("Available sessions:")
    for vf in view_files:
        name = vf.stem
        suffix = " (active)" if name == active_name else ""
        print(f"  - {name}{suffix}")
