from pathlib import Path

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
