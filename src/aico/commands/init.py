import sys
from pathlib import Path
from typing import Annotated

import typer

from aico.historystore import SessionView, save_view, switch_active_pointer
from aico.lib.session import SESSION_FILE_NAME


def init(
    model: Annotated[
        str,
        typer.Option(
            ...,
            "--model",
            "-m",
            help="The model to use for the session.",
        ),
    ] = "openrouter/google/gemini-2.5-pro",
) -> None:
    """
    Initialize a new session in the current directory.
    """
    session_file = Path.cwd() / SESSION_FILE_NAME
    if session_file.exists():
        print(
            f"Error: Session file '{session_file}' already exists in this directory.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    # Prepare shared-history directories
    project_root = session_file.parent
    history_root = project_root / ".aico" / "history"
    sessions_dir = project_root / ".aico" / "sessions"
    history_root.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Create an empty SessionView and point the pointer file at it
    view_path = sessions_dir / "main.json"
    view = SessionView(model=model, context_files=[], message_indices=[], history_start_pair=0, excluded_pairs=[])
    save_view(view_path, view)
    switch_active_pointer(session_file, view_path)

    print(f"Initialized session file: {session_file}")
