import sys
import warnings
from pathlib import Path
from typing import Annotated

import typer

from aico.addons import register_addon_commands
from aico.commands.history import history_app
from aico.commands.last import last
from aico.commands.prompt import prompt
from aico.commands.tokens import tokens_app
from aico.models import (
    SessionData,
)
from aico.utils import (
    SESSION_FILE_NAME,
    complete_files_in_context,
    get_relative_path_or_error,
    load_session,
    save_session,
)

app = typer.Typer()
app.add_typer(history_app, name="history")
app.add_typer(tokens_app, name="tokens")
_ = app.command("prompt")(prompt)
_ = app.command("last")(last)
register_addon_commands(app)


# Suppress warnings from litellm, see https://github.com/BerriAI/litellm/issues/11759
warnings.filterwarnings("ignore", category=UserWarning)


# Workaround for `no_args_is_help` not working, keep this until #1240 in typer is fixed
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        raise typer.Exit()


@app.command()
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
    Initializes a new AI session in the current directory.
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


@app.command()
def add(file_paths: list[Path]) -> None:
    """
    Adds one or more files to the context for the AI session.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent

    files_were_added = False
    errors_found = False

    for file_path in file_paths:
        if not file_path.is_file():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            errors_found = True
            continue

        relative_path_str = get_relative_path_or_error(file_path, session_root)

        if not relative_path_str:
            errors_found = True
            continue

        if relative_path_str not in session_data.context_files:
            session_data.context_files.append(relative_path_str)
            files_were_added = True
            print(f"Added file to context: {relative_path_str}")
        else:
            print(f"File already in context: {relative_path_str}")

    if files_were_added:
        session_data.context_files.sort()
        save_session(session_file, session_data)

    if errors_found:
        raise typer.Exit(code=1)


@app.command()
def drop(
    file_paths: Annotated[
        list[Path],
        typer.Argument(autocompletion=complete_files_in_context),
    ],
) -> None:
    """
    Drops one or more files from the context for the AI session.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent

    files_were_dropped = False
    errors_found = False

    new_context_files = session_data.context_files[:]

    for file_path in file_paths:
        relative_path_str = get_relative_path_or_error(file_path, session_root)

        if not relative_path_str:
            errors_found = True
            continue

        if relative_path_str in new_context_files:
            new_context_files.remove(relative_path_str)
            files_were_dropped = True
            print(f"Dropped file from context: {relative_path_str}")
        else:
            print(f"Error: File not in context: {file_path}", file=sys.stderr)
            errors_found = True

    if files_were_dropped:
        session_data.context_files = sorted(new_context_files)
        save_session(session_file, session_data)

    if errors_found:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
