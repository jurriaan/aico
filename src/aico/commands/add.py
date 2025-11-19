import sys
from pathlib import Path

import typer

from aico.core.session_loader import load_active_session
from aico.lib.session import get_relative_path_or_error


def add(file_paths: list[Path]) -> None:
    """
    Add file(s) to the session context.
    """
    session = load_active_session()

    files_to_add: list[str] = []
    current_files = set(session.data.context_files)
    errors_found = False

    for file_path in file_paths:
        if not file_path.is_file():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            errors_found = True
            continue

        relative_path_str = get_relative_path_or_error(file_path, session.root)
        if not relative_path_str:
            errors_found = True
            continue

        if relative_path_str in current_files:
            print(f"File already in context: {relative_path_str}")
        else:
            files_to_add.append(relative_path_str)
            print(f"Added file to context: {relative_path_str}")

    if files_to_add:
        new_context = sorted(current_files | set(files_to_add))
        session.persistence.update_view_metadata(context_files=new_context)

    if errors_found:
        raise typer.Exit(code=1)
