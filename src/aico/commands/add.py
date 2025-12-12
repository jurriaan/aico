from pathlib import Path

from aico.exceptions import InvalidInputError
from aico.fs import validate_input_paths
from aico.session import Session


def add(file_paths: list[Path]) -> None:
    session = Session.load_active()

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
        session.update_view_metadata(context_files=new_context)

    if errors_found:
        raise InvalidInputError("One or more files could not be added.")
