from pathlib import Path

import typer

from aico.core.files import validate_input_paths
from aico.core.session_loader import load_active_session


def add(file_paths: list[Path]) -> None:
    session = load_active_session()

    current_files = set(session.data.context_files)
    valid_rels, errors_found = validate_input_paths(session.root, file_paths, require_file_exists=True)

    files_to_add: list[str] = []
    for rel in valid_rels:
        if rel in current_files:
            print(f"File already in context: {rel}")
        else:
            files_to_add.append(rel)
            print(f"Added file to context: {rel}")

    if files_to_add:
        new_context = sorted(current_files | set(files_to_add))
        session.persistence.update_view_metadata(context_files=new_context)

    if errors_found:
        raise typer.Exit(code=1)
