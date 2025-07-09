import re
import warnings
from typing import final, override

import typer
from click import Context
from typer.core import TyperGroup

from aico.addons import register_addon_commands
from aico.commands.context import add, drop
from aico.commands.history import history_app
from aico.commands.init import init
from aico.commands.last import last
from aico.commands.prompt import ask, generate_patch, prompt
from aico.commands.tokens import tokens_app
from aico.commands.undo import undo


@final
class AliasGroup(TyperGroup):
    _CMD_SPLIT_P = re.compile(r" ?[,|] ?")

    @override
    def get_command(self, ctx: Context, cmd_name: str):
        cmd_name = self._group_cmd_name(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _group_cmd_name(self, default_name: str):
        for cmd in self.commands.values():
            name = cmd.name
            if name and default_name in self._CMD_SPLIT_P.split(name):
                return name
        return default_name


app = typer.Typer(cls=AliasGroup)
app.add_typer(history_app, name="history")
app.add_typer(tokens_app, name="tokens")
_ = app.command("ask")(ask)
_ = app.command("generate-patch | gen")(generate_patch)
_ = app.command("prompt")(prompt)
_ = app.command("last", context_settings={"ignore_unknown_options": True})(last)
_ = app.command("add")(add)
_ = app.command("drop")(drop)
_ = app.command("init")(init)
_ = app.command("undo", context_settings={"ignore_unknown_options": True})(undo)
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
