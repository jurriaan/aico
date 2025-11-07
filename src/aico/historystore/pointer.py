import json
from pathlib import Path
from typing import Literal

import typer
from pydantic import BaseModel, ValidationError


class SessionPointer(BaseModel):
    type: Literal["aico_session_pointer_v1"]
    path: str


def load_pointer(pointer_file: Path) -> Path:
    """
    Load and validate a shared-history session pointer file (.ai_session.json).
    Returns the absolute path to the referenced SessionView file.

    Exits with a user-friendly error if the pointer is invalid or the view is missing.
    """
    try:
        raw_text = pointer_file.read_text(encoding="utf-8")
        pointer = SessionPointer.model_validate_json(raw_text)
    except (ValidationError, json.JSONDecodeError) as e:
        typer.echo(
            f"Error: Not a valid shared-history pointer file: {pointer_file}.\nDetails: {e}",
            err=True,
        )
        raise typer.Exit(1) from e
    except OSError as e:
        typer.echo(f"Error: Could not read pointer file {pointer_file}: {e}", err=True)
        raise typer.Exit(1) from e

    view_path_abs = (pointer_file.parent / pointer.path).resolve()
    if not view_path_abs.is_file():
        typer.echo(f"Error: Session pointer refers to missing view file: {view_path_abs}", err=True)
        raise typer.Exit(1)
    return view_path_abs
