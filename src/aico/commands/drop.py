import sys
from pathlib import Path

from aico.exceptions import InvalidInputError
from aico.fs import validate_input_paths
from aico.session_loader import load_active_session


def drop(
    file_paths: list[Path],
) -> None:
    session = load_active_session()

    current_files = set(session.data.context_files)
    valid_rels, outside_root_errors = validate_input_paths(session.root, file_paths, require_file_exists=False)
    errors_found = outside_root_errors

    files_to_drop: list[str] = []
    for rel in valid_rels:
        if rel in current_files:
            files_to_drop.append(rel)
            print(f"Dropped file from context: {rel}")
        else:
            print(f"Error: File not in context: {rel}", file=sys.stderr)
            errors_found = True

    if files_to_drop:
        new_context = sorted(current_files - set(files_to_drop))
        session.persistence.update_view_metadata(context_files=new_context)

    if errors_found:
        raise InvalidInputError("One or more files described could not be dropped.")
