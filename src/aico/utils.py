import sys
from pathlib import Path

import typer
from pydantic import ValidationError

from aico.models import SessionData

SESSION_FILE_NAME = ".ai_session.json"


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
