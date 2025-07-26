import contextlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

from typer import Context, Typer

from aico.lib.models import AddonInfo
from aico.lib.session import find_session_file

# Constants for addon directories
_PROJECT_ADDONS_DIR = ".aico/addons"


def _get_addon_dirs_and_sources() -> list[tuple[Path, Literal["project", "user"]]]:
    """Returns a list of addon directories to search, project-level first."""
    dirs: list[tuple[Path, Literal["project", "user"]]] = []
    session_file = find_session_file()
    if session_file:
        project_dir = session_file.parent
        project_addons_path = project_dir / _PROJECT_ADDONS_DIR
        dirs.append((project_addons_path, "project"))

    user_addons_dir = Path.home() / ".config" / "aico" / "addons"
    dirs.append((user_addons_dir, "user"))

    return dirs


def _scan_dir_for_addons(
    addon_dir: Path,
    found_addons: dict[str, AddonInfo],
    source: Literal["project", "user"],
) -> None:
    if not addon_dir.is_dir():
        return

    for item in addon_dir.iterdir():
        if item.is_file() and os.access(item, os.X_OK):
            addon_name = item.name
            if addon_name not in found_addons:  # Project-level takes precedence
                try:
                    result = subprocess.run(
                        [str(item.resolve()), "--usage"],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        check=False,
                    )
                    # Take only the first line of output
                    help_text = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
                except (subprocess.TimeoutExpired, FileNotFoundError, IndexError):
                    help_text = ""

                found_addons[addon_name] = AddonInfo(
                    name=addon_name, path=item.resolve(), help_text=help_text, source=source
                )


def discover_addons() -> list[AddonInfo]:
    """Scans addon directories for executable scripts and returns info about them."""
    found_addons: dict[str, AddonInfo] = {}

    for addon_dir, source in _get_addon_dirs_and_sources():
        _scan_dir_for_addons(addon_dir, found_addons, source)

    return sorted(found_addons.values(), key=lambda addon: addon.name)


def execute_addon(addon: AddonInfo, args: list[str]) -> None:
    env = os.environ.copy()
    session_file = find_session_file()
    if session_file:
        env["AICO_SESSION_FILE"] = str(session_file.resolve())

    try:
        # The second argument to execvpe is the `argv` for the new process.
        # aico's argv: ['/path/to/aico', 'my-addon', 'arg1']
        # We want the addon's argv to be: ['my-addon', 'arg1']
        os.execvpe(addon.path, [addon.name] + args, env)
    except OSError as e:
        print(f"Error executing addon '{addon.name}': {e}", file=sys.stderr)
        # os.exec* replaces the process, so this exit is a fallback.
        sys.exit(1)


def register_addon_commands(app: Typer) -> None:
    """
    Registers the addons command group with the main application.
    """
    addons: list[AddonInfo] = []

    with contextlib.suppress(Exception):
        addons = discover_addons()

    def build_addon_command(addon: AddonInfo):
        def newfunc(context: Context) -> None:
            return execute_addon(addon, context.args)

        return newfunc

    command_names = {cmd.name for cmd in app.registered_commands if cmd.name}
    for addon in addons:
        if addon.name not in command_names:
            addon_command = build_addon_command(addon)

            addon_command.__name__ = addon.name
            addon_command.__doc__ = addon.help_text
            _ = app.command(
                name=addon.name,
                help=addon.help_text,
                rich_help_panel="Addons",
                add_help_option=False,
                context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
            )(addon_command)
