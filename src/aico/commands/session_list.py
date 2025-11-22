from pathlib import Path

import typer

from aico.core.session_loader import load_active_session
from aico.historystore.pointer import load_pointer


def session_list() -> None:
    session = load_active_session(require_type="shared")

    # Validate and resolve active view path via pointer helper
    active_view_path = load_pointer(session.file_path)

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
