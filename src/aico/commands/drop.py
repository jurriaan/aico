import sys
from pathlib import Path
from typing import Annotated

import typer

from aico.core.session_loader import load_active_session
from aico.lib.session import (
    complete_files_in_context,
    validate_input_paths,
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

    current_files = set(session.data.context_files)
    valid_rels, outside_root_errors = validate_input_paths(session.root, file_paths, require_file_exists=False)
    errors_found = outside_root_errors

    files_to_drop: list[str] = []
    for i, rel in enumerate(valid_rels):
        path = file_paths[i]
        if rel in current_files:
            files_to_drop.append(rel)
            print(f"Dropped file from context: {rel}")
        else:
            print(f"Error: File not in context: {path}", file=sys.stderr)
            errors_found = True

    if files_to_drop:
        new_context = sorted(current_files - set(files_to_drop))
        session.persistence.update_view_metadata(context_files=new_context)

    if errors_found:
        raise typer.Exit(code=1)
