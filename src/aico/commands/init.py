import sys
from pathlib import Path
from typing import Annotated

import typer

from aico.lib.models import SessionData
from aico.lib.session import SESSION_FILE_NAME, save_session


def init(
    model: Annotated[
        str,
        typer.Option(
            ...,
            "--model",
            "-m",
            help="The model to use for the session.",
        ),
    ] = "openrouter/google/gemini-2.5-pro",
) -> None:
    """
    Initialize a new session in the current directory.
    """
    session_file = Path.cwd() / SESSION_FILE_NAME
    if session_file.exists():
        print(
            f"Error: Session file '{session_file}' already exists in this directory.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    new_session = SessionData(model=model, chat_history=[], context_files=[])
    save_session(session_file, new_session)

    print(f"Initialized session file: {session_file}")
