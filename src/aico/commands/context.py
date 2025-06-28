import sys
from pathlib import Path
from typing import Annotated

import typer

from aico.utils import (
    complete_files_in_context,
    get_relative_path_or_error,
    load_session,
    save_session,
)


def add(file_paths: list[Path]) -> None:
    """
    Adds one or more files to the context for the AI session.
    """
    session_file, session_data = load_session()
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
        save_session(session_file, session_data)

    if errors_found:
        raise typer.Exit(code=1)


def drop(
    file_paths: Annotated[
        list[Path],
        typer.Argument(autocompletion=complete_files_in_context),
    ],
) -> None:
    """
    Drops one or more files from the context for the AI session.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent

    files_were_dropped = False
    errors_found = False

    new_context_files = session_data.context_files[:]

    for file_path in file_paths:
        relative_path_str = get_relative_path_or_error(file_path, session_root)

        if not relative_path_str:
            errors_found = True
            continue

        if relative_path_str in new_context_files:
            new_context_files.remove(relative_path_str)
            files_were_dropped = True
            print(f"Dropped file from context: {relative_path_str}")
        else:
            print(f"Error: File not in context: {file_path}", file=sys.stderr)
            errors_found = True

    if files_were_dropped:
        session_data.context_files = sorted(new_context_files)
        save_session(session_file, session_data)

    if errors_found:
        raise typer.Exit(code=1)
