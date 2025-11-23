from pathlib import Path
from typing import Annotated, final, override

import click
import typer
from click import Context
from typer.core import TyperGroup

from aico.lib.session_find import complete_files_in_context
from aico.prompts import DEFAULT_SYSTEM_PROMPT

app: typer.Typer


@final
class AliasGroup(TyperGroup):
    def _load_addons(self) -> None:
        """Lazily discovers and registers addons to this group instance."""
        from aico.addons import create_click_command, discover_addons

        for addon in discover_addons():
            if addon.name not in self.commands:
                self.add_command(create_click_command(addon), name=addon.name)

    @override
    def get_command(self, ctx: Context, cmd_name: str):
        # 1. Try Exact Match (Built-ins)
        cmd = super().get_command(ctx, cmd_name)
        if cmd:
            return cmd

        # 2. Try Pipe Alias Resolution (Built-ins with aliases)
        resolved_name = self._group_cmd_name(cmd_name)
        if resolved_name != cmd_name:
            cmd = super().get_command(ctx, resolved_name)
            if cmd:
                return cmd

        # 3. Fallback: Load Addons and Retry Exact Match
        self._load_addons()
        return super().get_command(ctx, cmd_name)

    @override
    def list_commands(self, ctx: Context):
        self._load_addons()
        # TyperGroup/Click logic handles sorting of self.commands
        return super().list_commands(ctx)

    @override
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        # Ensure addons are registered before help is formatted so they appear in the listing
        self._load_addons()
        return super().format_help(ctx, formatter)

    def _group_cmd_name(self, default_name: str):
        for cmd in self.commands.values():
            if cmd.name:
                aliases = [s.strip() for s in cmd.name.replace(",", "|").split("|") if s.strip()]
                if default_name in aliases:
                    return cmd.name
        return default_name


app = typer.Typer(cls=AliasGroup)


@app.command("status")
def status() -> None:
    """
    Show session status and token usage.
    """
    from aico.commands import status

    status.status()


@app.command("log")
def log() -> None:
    """
    Display the active conversation log.
    """
    from aico.commands import log

    log.log()


@app.command("set-history", context_settings={"ignore_unknown_options": True})
def set_history(
    pair_index_str: Annotated[
        str,
        typer.Argument(
            ...,
            help="The pair index to set as the start of the active context. "
            + "Use 0 to make the full history active. "
            + "Use negative numbers to count from the end. "
            + "Use the 'clear' to clear the context.",
        ),
    ],
) -> None:
    """
    Set the active window of the conversation history.

    Use `aico log` to see available pair indices.

    - `aico set-history 0` makes the full history active.
    - `aico set-history clear` clears the context for the next prompt.
    """
    from aico.commands import set_history

    set_history.set_history(pair_index_str)


@app.command("ask")
def ask(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[str, typer.Option(help="The system prompt to guide the AI.")] = DEFAULT_SYSTEM_PROMPT,
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    no_history: Annotated[
        bool,
        typer.Option(
            "--no-history",
            help="Do not include chat history in the prompt for this request.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Have a conversation for planning and discussion.
    """
    from aico.commands import prompt

    prompt.ask(cli_prompt_text, system_prompt, passthrough, no_history, model)


@app.command("dump-history")
def dump_history() -> None:
    """
    Export active chat history to stdout in a machine-readable format.
    """
    from aico.commands import dump_history

    dump_history.dump_history()


@app.command("generate-patch | gen", rich_help_panel=None)
def generate_patch(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[str, typer.Option(help="The system prompt to guide the AI.")] = DEFAULT_SYSTEM_PROMPT,
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    no_history: Annotated[
        bool,
        typer.Option(
            "--no-history",
            help="Do not include chat history in the prompt for this request.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Generate code modifications as a unified diff.
    """
    from aico.commands import prompt

    prompt.generate_patch(cli_prompt_text, system_prompt, passthrough, no_history, model)


@app.command("prompt")
def prompt(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[str, typer.Option(help="The system prompt to guide the AI.")] = DEFAULT_SYSTEM_PROMPT,
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    no_history: Annotated[
        bool,
        typer.Option(
            "--no-history",
            help="Do not include chat history in the prompt for this request.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Send a raw prompt to the AI.
    """
    from aico.commands import prompt

    prompt.prompt(cli_prompt_text, system_prompt, passthrough, no_history, model)


@app.command("last", context_settings={"ignore_unknown_options": True})
def last(
    index: Annotated[
        str,
        typer.Argument(
            help="The index of the message pair to show. Use negative numbers to count from the end "
            + "(e.g., -1 for the last pair).",
        ),
    ] = "-1",
    prompt: Annotated[
        bool,
        typer.Option(
            "--prompt",
            help="Show the user prompt instead of the assistant response.",
        ),
    ] = False,
    verbatim: Annotated[
        bool,
        typer.Option(
            "--verbatim",
            help="Show the verbatim response from the AI with no processing.",
        ),
    ] = False,
    recompute: Annotated[
        bool,
        typer.Option(
            "--recompute",
            "-r",
            help="Recalculate the response against the current state of files. Only valid for assistant responses.",
        ),
    ] = False,
) -> None:
    """
    Output the last response or diff to stdout.

    By default, it shows the assistant response from the last pair.
    Use INDEX to select a specific pair (e.g., 0 for the first, -1 for the last).
    Use --prompt to see the user's prompt instead of the AI's response.
    Use --recompute to re-apply an AI's instructions to the current file state.
    """
    from aico.commands import last

    last.last(index, prompt, verbatim, recompute)


@app.command("edit", context_settings={"ignore_unknown_options": True})
def edit(
    index: Annotated[
        str,
        typer.Argument(
            help="Index of the message pair to edit (e.g., -1 for last).",
        ),
    ] = "-1",
    prompt: Annotated[
        bool,
        typer.Option(
            "--prompt",
            help="Edit the user prompt instead of the assistant response.",
        ),
    ] = False,
) -> None:
    """
    Open a message in your default editor ($EDITOR) to make corrections.
    """
    from aico.commands import edit

    edit.edit(index, prompt)


@app.command("add")
def add(
    file_paths: Annotated[
        list[Path],
        typer.Argument(
            help="Paths to files to add to the context.",
        ),
    ],
) -> None:
    """
    Add file(s) to the session context.
    """
    from aico.commands import add

    add.add(file_paths)


@app.command("drop")
def drop(
    file_paths: Annotated[
        list[Path],
        typer.Argument(autocompletion=complete_files_in_context),
    ],
) -> None:
    """
    Remove file(s) from the session context.
    """
    from aico.commands import drop

    drop.drop(file_paths)


@app.command("init")
def init(
    model: Annotated[
        str,
        typer.Option(
            ...,
            "--model",
            "-m",
            help="The model to use for the session.",
        ),
    ] = "openrouter/google/gemini-3-pro-preview",
) -> None:
    """
    Initialize a new session in the current directory.
    """
    from aico.commands import init

    init.init(model)


@app.command("undo", context_settings={"ignore_unknown_options": True})
def undo(
    indices: Annotated[
        list[str] | None,
        typer.Argument(
            help="The indices of the message pairs to undo. "
            + "Supports single IDs ('1', '-1'), lists ('1' '5'), "
            + "and inclusive ranges ('1..5', '-3..-1'). Defaults to -1.",
        ),
    ] = None,
) -> None:
    """
    Exclude one or more message pairs from the context [default: last].

    This command performs a "soft delete" on the pairs at the given INDICES.
    The messages are not removed from the history, but are flagged to be
    ignored when building the context for the next prompt.
    """
    from aico.commands import undo

    undo.undo(indices)


@app.command("redo", context_settings={"ignore_unknown_options": True})
def redo(
    indices: Annotated[
        list[str] | None,
        typer.Argument(
            help="Indices of the message pairs to redo. "
            + "Supports single IDs ('1', '-1'), lists ('1' '5'), "
            + "and inclusive ranges ('1..5', '-3..-1'). Defaults to -1 (last).",
        ),
    ] = None,
) -> None:
    """
    Re-include one or more message pairs in context.
    """
    from aico.commands import redo

    redo.redo(indices)


@app.command("session-list")
def session_list() -> None:
    """
    List available session views (branches) for a shared-history session.
    """
    from aico.commands import session_list

    session_list.session_list()


@app.command("session-switch")
def session_switch(
    name: Annotated[str, typer.Argument(help="Name of the session view (branch) to activate.")],
) -> None:
    """
    Switch the active session pointer to another existing view (branch).
    """
    from aico.commands import session_switch

    session_switch.session_switch(name)


@app.command("session-fork")
def session_fork(
    new_name: Annotated[str, typer.Argument(help="Name for the new forked session view (branch).")],
    until_pair: Annotated[
        int | None,
        typer.Option(
            "--until-pair",
            help="Optional pair index to truncate history at (inclusive). If omitted, full history is copied.",
        ),
    ] = None,
) -> None:
    """
    Create a new session view (branch) optionally truncated at a given pair index, then switch to it.
    """
    from aico.commands import session_fork

    session_fork.session_fork(new_name, until_pair)


@app.command("session-new")
def session_new(
    name: Annotated[str, typer.Argument(help="Name for the new, empty session view (branch).")],
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="The model to use for the new session. If omitted, inherits from the current session.",
        ),
    ] = None,
) -> None:
    """
    Create a new, empty session view (branch) and switch to it.
    """
    from aico.commands import session_new

    session_new.session_new(name, model)


@app.command("migrate-shared-history")
def migrate_shared_history(
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help="Name for the new session view (branch).",
        ),
    ] = "main",
    backup: Annotated[
        bool,
        typer.Option(
            "--backup/--no-backup",
            help="Create a backup of the legacy session file before migrating.",
        ),
    ] = True,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing view file with the same name if it exists.",
        ),
    ] = False,
) -> None:
    """
    Migrate a legacy single-file session (.ai_session.json) to the shared-history format.

    Creates:
      - .aico/history/ (sharded history records)
      - .aico/sessions/<name>.json (session view)
      - Rewrites .ai_session.json as a pointer to the new view
    """
    from aico.commands import migrate_shared_history

    migrate_shared_history.migrate_shared_history(name, backup, force)


@app.command("dump-context")
def dump_context() -> None:
    """
    Export the session context in a structured, machine-readable JSON format.
    """
    from aico.commands import dump_context

    dump_context.dump_context()


# Workaround for `no_args_is_help` not working, keep this until #1240 in typer is fixed
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
