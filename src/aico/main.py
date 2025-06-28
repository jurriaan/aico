import sys
import warnings
from pathlib import Path
from typing import Annotated

import typer

from aico.addons import register_addon_commands
from aico.commands.context import add, drop
from aico.commands.history import history_app
from aico.commands.last import last
from aico.commands.prompt import prompt
from aico.commands.tokens import tokens_app
from aico.models import (
    SessionData,
)
from aico.utils import (
    SESSION_FILE_NAME,
    save_session,
)

app = typer.Typer()
app.add_typer(history_app, name="history")
app.add_typer(tokens_app, name="tokens")
_ = app.command("prompt")(prompt)
_ = app.command("last")(last)
_ = app.command("add")(add)
_ = app.command("drop")(drop)
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


if __name__ == "__main__":
    app()
