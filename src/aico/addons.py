import contextlib
import importlib.resources
import os
import stat
import subprocess
import sys
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

from typer import Context, Typer

from aico.lib.atomic_io import atomic_write_text
from aico.lib.models import AddonInfo
from aico.lib.session import find_session_file

# Constants for addon directories
_PROJECT_ADDONS_DIR = ".aico/addons"


def _get_user_cache_dir() -> Path:
    """Returns the cache directory for extracted bundled addons."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    cache_dir = base / "aico" / "bundled_addons"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _extract_bundled_addon(item: Traversable) -> Path:
    """Extracts a bundled addon to cache, makes executable, returns Path."""
    cache_dir = _get_user_cache_dir()
    target = cache_dir / item.name
    content_bytes = item.read_bytes()
    atomic_write_text(target, content_bytes)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def _run_usage(file_path: Path) -> str:
    """Runs --usage on an executable file path, returns first line of stdout."""
    try:
        result = subprocess.run(
            [str(file_path), "--usage"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, IndexError, OSError):
        return ""


def _get_addon_dirs_and_sources() -> list[tuple[Path | Traversable, Literal["project", "user", "bundled"]]]:
    """Returns a list of addon directories to search, project-level first."""
    dirs: list[tuple[Path | Traversable, Literal["project", "user", "bundled"]]] = []
    session_file = find_session_file()
    if session_file:
        project_dir = session_file.parent
        project_addons_path = project_dir / _PROJECT_ADDONS_DIR
        dirs.append((project_addons_path, "project"))

    user_addons_dir = Path.home() / ".config" / "aico" / "addons"
    dirs.append((user_addons_dir, "user"))

    # Bundled addons (lowest priority)
    try:
        bundled_dir = importlib.resources.files("aico.bundled_addons")
        dirs.append((bundled_dir, "bundled"))
    except Exception:
        pass

    return dirs


def _scan_dir_for_addons(
    addon_dir: Path | Traversable,
    found_addons: dict[str, AddonInfo],
    source: Literal["project", "user", "bundled"],
) -> None:
    if not addon_dir.is_dir():
        return

    for item in addon_dir.iterdir():
        if not item.is_file():
            continue

        if source == "bundled":
            # Exclude typical python artifacts from resource iteration
            if item.name.startswith("__") or item.name.endswith(".pyc"):
                continue
            try:
                file_path = _extract_bundled_addon(item)
            except Exception:
                continue
        else:
            # Project and user addons must be Path objects and executable
            if isinstance(item, Path) and os.access(item, os.X_OK):
                file_path = item
            else:
                continue

        addon_name = file_path.name
        if addon_name in found_addons:
            continue

        help_text = _run_usage(file_path)
        found_addons[addon_name] = AddonInfo(name=addon_name, path=file_path, help_text=help_text, source=source)


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

    # Propagate the parent's sys.path to the addon's PYTHONPATH. This ensures
    # the addon has the same module resolution environment as the main `aico`
    # process, allowing it to import `aico` library modules even when
    # running from a source checkout.
    env["PYTHONPATH"] = os.pathsep.join(sys.path)

    # Ensure addons that use `#!/usr/bin/env python` find the same Python
    # interpreter that is running `aico`. This is crucial when aico is run
    # via a tool like `uv`, which doesn't always put its shims first in PATH.
    current_python_executable_dir = str(Path(sys.executable).parent)
    original_path = env.get("PATH", "")
    env["PATH"] = f"{current_python_executable_dir}{os.pathsep}{original_path}"

    try:
        # All addon paths are now guaranteed executable Paths on disk
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
