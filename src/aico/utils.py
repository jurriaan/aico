import sys
from pathlib import Path

import typer
from pydantic import ValidationError

from aico.models import SessionData

SESSION_FILE_NAME = ".ai_session.json"
DIFF_MODE_INSTRUCTIONS = (
    "\n\n---\n"
    "IMPORTANT: You are an automated code generation tool. Your response MUST ONLY contain one or more raw SEARCH/REPLACE blocks. "
    "You MUST NOT add any other text, commentary, or markdown. "
    "Your entire response must strictly follow the format specified below.\n"
    "- To create a new file, use an empty SEARCH block.\n"
    "- To delete a file, provide a SEARCH block with the entire file content and an empty REPLACE block.\n\n"
    "EXAMPLE of a multi-file change:\n"
    "File: path/to/existing/file.py\n"
    "<<<<<<< SEARCH\n"
    "    # code to be changed\n"
    "=======\n"
    "    # the new code\n"
    ">>>>>>> REPLACE\n"
    "File: path/to/new/file.py\n"
    "<<<<<<< SEARCH\n"
    "=======\n"
    "def new_function():\n"
    "    pass\n"
    ">>>>>>> REPLACE"
)


def find_session_file() -> Path | None:
    """
    Finds the .ai_session.json file by searching upward from the current directory.
    """
    current_dir = Path.cwd().resolve()
    while True:
        session_file = current_dir / SESSION_FILE_NAME
        if session_file.is_file():
            return session_file
        if current_dir.parent == current_dir:  # Reached the filesystem root
            return None
        current_dir = current_dir.parent


def format_tokens(tokens: int) -> str:
    """Formats token counts for display, using 'k' for thousands."""
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


def load_session() -> tuple[Path, SessionData]:
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. "
            "Please run 'aico init' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    try:
        session_data = SessionData.model_validate_json(session_file.read_text())
    except ValidationError:
        print(
            "Error: Session file is corrupt or has an invalid format.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    return session_file, session_data


def get_relative_path_or_error(file_path: Path, session_root: Path) -> str | None:
    abs_file_path = file_path.resolve()

    try:
        relative_path = abs_file_path.relative_to(session_root)
        return str(relative_path)
    except ValueError:
        print(
            f"Error: File '{abs_file_path}' is outside the session root '{session_root}'. Files must be within the same directory tree as the session file.",
            file=sys.stderr,
        )
        return None
