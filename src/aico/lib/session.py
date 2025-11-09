import os
import sys
from json import JSONDecodeError
from pathlib import Path
from tempfile import mkstemp

import typer
from pydantic import TypeAdapter, ValidationError

from aico.lib.models import FileContents, SessionData

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
    abs_file_path = file_path.resolve()

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
    session_file = find_session_file()
    if not session_file:
        return []

    try:
        session_data = SessionDataAdapter.validate_json(session_file.read_text())
        completions = [f for f in session_data.context_files if f.startswith(incomplete)]
        completions += [f for f in session_data.context_files if incomplete in f and f not in completions]
        return completions
    except (ValidationError, JSONDecodeError):
        return []


def save_session(session_file: Path, session_data: SessionData) -> None:
    fd, tmp = mkstemp(suffix=".json", prefix=session_file.name + ".tmp", dir=session_file.parent)
    session_file_tmp = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as f:
            _ = f.write(SessionDataAdapter.dump_json(session_data, indent=2))
        os.replace(session_file_tmp, session_file)
    finally:
        session_file_tmp.unlink(missing_ok=True)


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
