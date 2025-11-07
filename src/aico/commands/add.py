import sys
from pathlib import Path

import typer

from aico.core.session_persistence import get_persistence
from aico.lib.session import get_relative_path_or_error


def add(file_paths: list[Path]) -> None:
    """
    Add file(s) to the session context.
    """
    persistence = get_persistence()
    session_file, session_data = persistence.load()
    session_root = session_file.parent

    files_were_added = False
    errors_found = False

    for file_path in file_paths:
        if not file_path.is_file():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            errors_found = True
            continue

        relative_path_str = get_relative_path_or_error(file_path, session_root)

        if not relative_path_str:
            errors_found = True
            continue

        if relative_path_str not in session_data.context_files:
            session_data.context_files.append(relative_path_str)
            files_were_added = True
            print(f"Added file to context: {relative_path_str}")
        else:
            print(f"File already in context: {relative_path_str}")

    if files_were_added:
        session_data.context_files.sort()
        persistence.save(session_file, session_data)

    if errors_found:
        raise typer.Exit(code=1)
