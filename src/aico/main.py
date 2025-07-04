import warnings

import typer

from aico.addons import register_addon_commands
from aico.commands.context import add, drop
from aico.commands.history import history_app
from aico.commands.init import init
from aico.commands.last import last
from aico.commands.prompt import ask, edit, prompt
from aico.commands.tokens import tokens_app
from aico.commands.undo import undo

app = typer.Typer()
app.add_typer(history_app, name="history")
app.add_typer(tokens_app, name="tokens")
_ = app.command("ask")(ask)
_ = app.command("edit")(edit)
_ = app.command("prompt")(prompt)
_ = app.command("last")(last)
_ = app.command("add")(add)
_ = app.command("drop")(drop)
_ = app.command("init")(init)
_ = app.command("undo")(undo)
register_addon_commands(app)


# Suppress warnings from litellm, see https://github.com/BerriAI/litellm/issues/11759
warnings.filterwarnings("ignore", category=UserWarning)


# Workaround for `no_args_is_help` not working, keep this until #1240 in typer is fixed
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
