from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from aico.core.trust import (
    is_project_trusted,
    list_trusted_projects,
    trust_project,
    untrust_project,
)


def trust(
    path: Annotated[
        Path | None, typer.Argument(help="The project path to trust. Defaults to current directory.")
    ] = None,
    revoke: Annotated[bool, typer.Option("--revoke", "--untrust", help="Revoke trust for the specified path.")] = False,
    show_list: Annotated[bool, typer.Option("--list", help="List all trusted project paths.")] = False,
) -> None:
    """
    Manage trusted projects for addon execution.

    By default, `aico` ignores project-local addons (.aico/addons) to prevent
    remote code execution from malicious repositories. Use this command to
    whitelist projects you trust.
    """
    console = Console()

    # Handle --list
    if show_list:
        trusted = list_trusted_projects()
        if not trusted:
            console.print("No trusted projects found.")
        else:
            console.print("[bold]Trusted Projects:[/bold]")
            for p in trusted:
                console.print(f"  - {p}")
        return

    # Determine target path (default to CWD)
    target_path = path if path else Path.cwd()

    # Resolve to check existence
    try:
        target_path = target_path.resolve()
    except OSError as e:
        console.print(f"[red]Error:[/red] Invalid path '{target_path}'.")
        raise typer.Exit(1) from e

    if not target_path.is_dir():
        console.print(f"[red]Error:[/red] Path is not a directory: {target_path}")
        raise typer.Exit(1)

    # Handle --revoke
    if revoke:
        if untrust_project(target_path):
            console.print(f"[green]Success:[/green] Revoked trust for: [bold]{target_path}[/bold]")
        else:
            console.print(f"[yellow]Warning:[/yellow] Path was not trusted: {target_path}")
        return

    # Handle Trust (Default action)
    if is_project_trusted(target_path):
        console.print(f"Project is already trusted: [bold]{target_path}[/bold]")
    else:
        trust_project(target_path)
        console.print(f"[green]Success:[/green] Trusted project: [bold]{target_path}[/bold]")
        console.print("[dim]Local addons in .aico/addons/ will now be loaded.[/dim]")
