from pathlib import Path
from typing import final

from aico.models import SessionPointer
from aico.serialization import from_json


@final
class InvalidPointerError(Exception):
    """Raised when a pointer file is not a valid shared-history SessionPointer."""

    def __init__(self, pointer_file: Path, details: object | None = None) -> None:
        msg = f"Not a valid shared-history pointer file: {pointer_file}"
        if details is not None:
            msg = f"{msg} ({details})"
        super().__init__(msg)
        self.pointer_file = pointer_file
        self.details = details


@final
class MissingViewError(Exception):
    """Raised when a pointer refers to a view file that does not exist."""

    def __init__(self, view_path: Path) -> None:
        super().__init__(f"Session pointer refers to missing view file: {view_path}")
        self.view_path = view_path


def load_pointer(pointer_file: Path) -> Path:
    """
    Load and validate a shared-history session pointer file (.ai_session.json).
    Returns the absolute path to the referenced SessionView file.

    Raises:
        InvalidPointerError: if the file cannot be parsed as a valid SessionPointer.
        MissingViewError: if the referenced view file does not exist.
        OSError: if the pointer file cannot be read.
    """
    try:
        raw_text = pointer_file.read_text(encoding="utf-8")

        pointer = from_json(SessionPointer, raw_text)

        if pointer["type"] != "aico_session_pointer_v1":
            raise InvalidPointerError(pointer_file)
    except OSError:
        # Propagate IO errors; callers decide how to surface them.
        raise
    except Exception as e:
        # Catch msgspec decode/type errors
        raise InvalidPointerError(pointer_file, e) from e

    view_path_abs = (pointer_file.parent / pointer["path"]).resolve()
    if not view_path_abs.is_file():
        raise MissingViewError(view_path_abs)
    return view_path_abs
