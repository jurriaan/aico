import os
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from typer import Context

from aico.consts import SESSION_FILE_NAME
from aico.exceptions import ConfigurationError
from aico.lib.models import SessionData, SessionPointer


def find_session_file() -> Path | None:
    """
    Locates the session file by checking AICO_SESSION_FILE or searching parents.
    """
    if env_path := os.environ.get("AICO_SESSION_FILE"):
        path = Path(env_path)
        if not path.is_absolute():
            raise ConfigurationError("AICO_SESSION_FILE must be an absolute path")
        if not path.exists():
            raise ConfigurationError(f"Session file specified in AICO_SESSION_FILE does not exist: {path}")
        return path

    current = Path.cwd()
    for parent in [current, *current.parents]:
        check = parent / SESSION_FILE_NAME
        if check.is_file():
            return check
    return None


def complete_files_in_context(ctx: Context | None, args: list[str], incomplete: str) -> list[str]:  # pyright: ignore[reportUnusedParameter]
    """
    Typer autocompletion callback. Returns list of files currently in context.
    """

    session_file = find_session_file()
    if not session_file:
        return []

    context_files: list[str] = []

    try:
        raw_text = session_file.read_text(encoding="utf-8").strip()
        if not raw_text:
            return []

        # 1. Attempt to parse as a Shared History Pointer
        # We check for the discriminator field first to avoid Pydantic validation ambiguity
        if '"aico_session_pointer_v1"' in raw_text:
            try:
                pointer = TypeAdapter(SessionPointer).validate_json(raw_text)
                view_path = (session_file.parent / pointer["path"]).resolve()
                if view_path.is_file():
                    # The view file is a lightweight JSON (SessionView), but we can
                    # largely treat it like SessionData structure for context_files
                    # or use json.loads if SessionView model isn't available here to avoid circular imports.
                    # Ideally, we use a specific model, but loose parsing for just this field is safe enough via
                    # SessionData adapter fallback or just direct read if we want to be minimal.
                    # Let's use SessionData adapter as a generic schema reader since views are compatible subsets.
                    view_data = TypeAdapter(SessionData).validate_json(view_path.read_text(encoding="utf-8"))
                    context_files = view_data.context_files
            except (ValidationError, OSError):
                pass

    except OSError:
        return []

    return [f for f in context_files if f.startswith(incomplete)]
