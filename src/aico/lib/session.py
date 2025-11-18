import json
import os
import sys
from json import JSONDecodeError
from pathlib import Path

import typer
from pydantic import TypeAdapter, ValidationError

from aico.historystore import load_view
from aico.historystore.pointer import SessionPointer
from aico.lib.models import FileContents, SessionData
from aico.utils import atomic_write_text

SESSION_FILE_NAME = ".ai_session.json"


def find_session_file() -> Path | None:
    """
    Finds the .ai_session.json file by checking the AICO_SESSION_FILE environment variable first,
    then searching upward from the current directory.
    """
    # Check environment variable first
    if session_path := os.getenv("AICO_SESSION_FILE"):
        session_file = Path(session_path)
        if not session_file.is_absolute():
            print(f"Error: AICO_SESSION_FILE must be an absolute path, got: {session_path}", file=sys.stderr)
            raise typer.Exit(code=1)
        if not session_file.is_file():
            print(f"Error: Session file specified in AICO_SESSION_FILE does not exist: {session_path}", file=sys.stderr)
            raise typer.Exit(code=1)
        return session_file

    # Fall back to upward search from current directory
    current_dir = Path.cwd().resolve()
    while True:
        session_file = current_dir / SESSION_FILE_NAME
        if session_file.is_file():
            return session_file
        if current_dir.parent == current_dir:  # Reached the filesystem root
            return None
        current_dir = current_dir.parent


SessionDataAdapter = TypeAdapter(SessionData)


def get_relative_path_or_error(file_path: Path, session_root: Path) -> str | None:
    abs_file_path = Path(os.path.normpath(file_path.absolute().as_posix()))

    try:
        relative_path = abs_file_path.relative_to(session_root)
        return str(relative_path)
    except ValueError:
        print(
            f"Error: File '{abs_file_path}' is outside the session root '{session_root}'. "
            + "Files must be within the same directory tree as the session file.",
            file=sys.stderr,
        )
        return None


def complete_files_in_context(incomplete: str) -> list[str]:
    """Provides shell completion for filenames currently in the session context."""
    session_file = find_session_file()
    if not session_file:
        return []

    context_files: list[str] = []
    try:
        raw_text = session_file.read_text(encoding="utf-8").strip()
        if not raw_text:
            return []

        # Attempt to parse as a shared-history pointer
        if "aico_session_pointer_v1" in raw_text:
            try:
                pointer = SessionPointer.model_validate_json(raw_text)
                view_path = (session_file.parent / pointer.path).resolve()
                if view_path.is_file():
                    view = load_view(view_path)
                    context_files = view.context_files
            except (ValidationError, json.JSONDecodeError):
                # It looked like a pointer but wasn't. Fall through to legacy parsing.
                pass

        # Fallback for legacy session files or failed pointer parsing
        if not context_files:
            session_data = SessionDataAdapter.validate_json(raw_text)
            context_files = session_data.context_files

    except (ValidationError, JSONDecodeError, OSError):
        return []

    # Build the list of completions, prioritizing prefix matches
    completions = [f for f in context_files if f.startswith(incomplete)]
    completions += [f for f in context_files if incomplete in f and f not in completions]
    return completions


def save_session(session_file: Path, session_data: SessionData) -> None:
    text = SessionDataAdapter.dump_json(session_data, indent=2)
    atomic_write_text(session_file, text)


def build_original_file_contents(context_files: list[str], session_root: Path) -> FileContents:
    original_file_contents: FileContents = {
        relative_path_str: abs_path.read_text()
        for relative_path_str in context_files
        if (abs_path := session_root / relative_path_str).is_file()
    }

    missing_files = set(context_files) - original_file_contents.keys()
    if missing_files:
        missing_list = " ".join(sorted(list(missing_files)))
        print(f"Warning: Context files not found, skipping: {missing_list}", file=sys.stderr)

    return original_file_contents
