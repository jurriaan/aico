import sys
from pathlib import Path
from typing import Annotated

import typer

from aico.core.session_loader import load_active_session
from aico.lib.session import (
    complete_files_in_context,
    get_relative_path_or_error,
)


def drop(
    file_paths: Annotated[
        list[Path],
        typer.Argument(autocompletion=complete_files_in_context),
    ],
) -> None:
    """
    Remove file(s) from the session context.
    """
    session = load_active_session()

    files_were_dropped = False
    errors_found = False

    new_context_files = session.data.context_files[:]

    for file_path in file_paths:
        relative_path_str = get_relative_path_or_error(file_path, session.root)

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
        session.persistence.update_view_metadata(context_files=sorted(new_context_files))

    if errors_found:
        raise typer.Exit(code=1)
