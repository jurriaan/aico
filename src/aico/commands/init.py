import sys
from pathlib import Path

import typer

from aico.consts import SESSION_FILE_NAME
from aico.historystore import SessionView, save_view, switch_active_pointer


def init(
    model: str,
) -> None:
    session_file = Path.cwd() / SESSION_FILE_NAME
    if session_file.exists():
        print(
            f"Error: Session file '{session_file}' already exists in this directory.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    # Prepare shared-history directories
    project_root = session_file.parent
    aico_dir = project_root / ".aico"
    history_root = aico_dir / "history"
    sessions_dir = aico_dir / "sessions"
    history_root.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    gitignore_path = aico_dir / ".gitignore"
    if not gitignore_path.exists():
        # 1. Ignore everything (*)
        # 2. Unignore addons folder (!addons/)
        # 3. Unignore this file (!.gitignore)
        gitignore_content = "*\n!addons/\n!.gitignore\n"
        _ = gitignore_path.write_text(gitignore_content, encoding="utf-8")

    # Create an empty SessionView and point the pointer file at it
    view_path = sessions_dir / "main.json"
    view = SessionView(model=model, context_files=[], message_indices=[], history_start_pair=0, excluded_pairs=[])
    save_view(view_path, view)
    switch_active_pointer(session_file, view_path)

    print(f"Initialized session file: {session_file}")
