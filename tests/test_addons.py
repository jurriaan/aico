# pyright: standard
from pathlib import Path

import typer
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.addons import discover_addons, execute_addon, register_addon_commands
from aico.lib.models import AddonInfo, SessionData
from aico.lib.session import SESSION_FILE_NAME, save_session

runner = CliRunner()


def _create_addon(dir_path: Path, name: str, help_text: str) -> Path:
    addon_path = dir_path / name
    # Addon script must handle --usage and be executable
    addon_path.write_text(f'#!/bin/sh\n[ "$1" = "--usage" ] && echo "{help_text}" || exit 0')
    addon_path.chmod(0o755)
    return addon_path


def test_register_addon_and_execute(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a Typer app and a mocked `execute_addon`
    app = typer.Typer()
    mock_execute = mocker.patch("aico.addons.execute_addon")

    # AND multiple fake addons are discovered
    addon1_path = tmp_path / "addon1"
    addon1_info = AddonInfo(name="addon1", path=addon1_path, help_text="Addon 1", source="project")
    addon2_path = tmp_path / "addon2"
    addon2_info = AddonInfo(name="addon2", path=addon2_path, help_text="Addon 2", source="project")
    mocker.patch("aico.addons.discover_addons", return_value=[addon1_info, addon2_info])

    # WHEN addons are registered with the app
    register_addon_commands(app)

    # AND the second addon command is invoked
    result = runner.invoke(app, ["addon2", "arg1", "--flag"])

    # THEN the command invocation succeeds
    assert result.exit_code == 0

    # AND `execute_addon` was called with the correct AddonInfo for the second addon
    mock_execute.assert_called_once_with(addon2_info, ["arg1", "--flag"])


def test_register_addon_does_not_override_builtin(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a Typer app with a built-in command
    app = typer.Typer()

    @app.command(name="dummy")
    def _dummy() -> None:
        pass

    @app.command(name="init")
    def _init() -> None:
        """A built-in command."""
        print("built-in init called")

    # AND an addon with the same name as the built-in
    addon_info = AddonInfo(name="init", path=tmp_path / "init", help_text="addon init help", source="project")
    mocker.patch("aico.addons.discover_addons", return_value=[addon_info])

    # WHEN addons are registered
    register_addon_commands(app)

    # AND the command is invoked
    result = runner.invoke(app, ["init"])

    # THEN the built-in function was called, not the addon
    print("Result:", result.stderr)
    assert result.exit_code == 0
    assert "built-in init called" in result.stdout

    # AND the help text shows the built-in command, not the addon
    help_result = runner.invoke(app, ["--help"])
    assert "Usage: root" in help_result.stdout
    assert "A built-in command." in help_result.stdout
    assert "addon init help" not in help_result.stdout


def test_execute_addon_calls_execvpe(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an addon info object
    addon_path = tmp_path / "my-addon"
    addon_info = AddonInfo(name="my-addon", path=addon_path, help_text="", source="project")

    # AND a session file
    session_file = tmp_path / SESSION_FILE_NAME
    save_session(session_file, SessionData(model="test", chat_history=[], context_files=[]))
    mocker.patch("aico.addons.find_session_file", return_value=session_file)

    # AND os.execvpe is mocked
    mock_exec = mocker.patch("os.execvpe")

    # WHEN execute_addon is called
    execute_addon(addon_info, ["arg1", "--flag"])

    # THEN os.execvpe is called with the correct path, arguments, and environment
    mock_exec.assert_called_once()
    call_args, _ = mock_exec.call_args
    assert call_args[0] == addon_path
    assert call_args[1] == ["my-addon", "arg1", "--flag"]  # `execute_addon` prepends the name
    env = call_args[2]
    assert "AICO_SESSION_FILE" in env
    assert env["AICO_SESSION_FILE"] == str(session_file.resolve())


def test_execute_addon_handles_os_error(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an addon info object
    addon_path = tmp_path / "my-addon"
    addon_info = AddonInfo(name="my-addon", path=addon_path, help_text="", source="project")

    # AND a session file exists (so the env var can be set)
    session_file = tmp_path / SESSION_FILE_NAME
    mocker.patch("aico.addons.find_session_file", return_value=session_file)

    # AND os.execvpe is mocked to raise an OSError
    mock_exec = mocker.patch("os.execvpe", side_effect=OSError("Test error"))
    mock_exit = mocker.patch("sys.exit")

    # WHEN execute_addon is called
    execute_addon(addon_info, [])

    # THEN the error is handled and sys.exit is called
    mock_exec.assert_called_once()
    mock_exit.assert_called_once_with(1)


def test_discover_addons(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a project addon and a user addon (with one name collision)
    session_file = tmp_path / SESSION_FILE_NAME
    save_session(session_file, SessionData(model="test", chat_history=[], context_files=[]))
    mocker.patch("aico.addons.find_session_file", return_value=session_file)

    # Mock the home directory to control user addons path
    user_home_dir = tmp_path / "user_home"
    user_home_dir.mkdir()
    mocker.patch("pathlib.Path.home", return_value=user_home_dir)

    # AND project addons
    project_addons_dir = tmp_path / ".aico" / "addons"
    project_addons_dir.mkdir(parents=True)
    project_addon_z_path = _create_addon(project_addons_dir, "z-addon", "Project Z help")
    collision_addon_path = _create_addon(project_addons_dir, "collision-addon", "Project collision help")
    non_executable_path = project_addons_dir / "not-executable"
    non_executable_path.write_text("...")

    # AND user addons
    user_addons_dir = user_home_dir / ".config" / "aico" / "addons"
    user_addons_dir.mkdir(parents=True)
    user_addon_a_path = _create_addon(user_addons_dir, "a-addon", "User A help")
    _create_addon(
        user_addons_dir, "collision-addon", "User collision help"
    )  # This is overridden by project collision-addon

    # Mock `importlib.resources.files` to point to a temporary bundled_addons directory
    mock_bundled_resources_path = tmp_path / "src" / "aico" / "bundled_addons"
    mock_bundled_resources_path.mkdir(parents=True, exist_ok=True)
    _create_addon(mock_bundled_resources_path, "commit", "Bundled commit help")
    _create_addon(mock_bundled_resources_path, "manage-context", "Bundled manage-context help")
    _create_addon(mock_bundled_resources_path, "summarize", "Bundled summarize help")

    # This mock needs to return an object that behaves like a Traversable, specifically `is_dir()` and `iterdir()`.
    # `files` returns a Traversable, which in a real scenario would represent a directory in the package.
    # The `iterdir` method of the mock should return mock Traversable items for each file.
    mock_bundled_traversable = mocker.MagicMock(spec=Path)  # Using Path as spec for real methods like is_dir
    mock_bundled_traversable.is_dir.return_value = True

    # Create mock Traversable objects for bundled addons
    mock_commit_item = mocker.MagicMock(spec=Path, name="commit")  # Use Path as spec for is_file()
    mock_commit_item.name = "commit"
    mock_commit_item.is_file.return_value = True
    mock_commit_item.read_bytes.return_value = (
        b'#!/bin/sh\n[ "$1" = "--usage" ] && echo "Bundled commit help" || exit 0'
    )

    mock_manage_context_item = mocker.MagicMock(spec=Path, name="manage-context")
    mock_manage_context_item.name = "manage-context"
    mock_manage_context_item.is_file.return_value = True
    mock_manage_context_item.read_bytes.return_value = (
        b'#!/bin/sh\n[ "$1" = "--usage" ] && echo "Bundled manage-context help" || exit 0'
    )

    mock_summarize_item = mocker.MagicMock(spec=Path, name="summarize")
    mock_summarize_item.name = "summarize"
    mock_summarize_item.is_file.return_value = True
    mock_summarize_item.read_bytes.return_value = (
        b'#!/bin/sh\n[ "$1" = "--usage" ] && echo "Bundled summarize help" || exit 0'
    )

    mock_bundled_traversable.iterdir.return_value = [mock_commit_item, mock_manage_context_item, mock_summarize_item]
    mocker.patch("importlib.resources.files", return_value=mock_bundled_traversable)

    # Mock the _get_user_cache_dir to ensure _extract_bundled_addon puts files where we expect
    mocker.patch("aico.addons._get_user_cache_dir", return_value=tmp_path / "cache" / "aico" / "bundled_addons")

    # WHEN addons are discovered
    addons = discover_addons()

    # THEN the correct addons are found, with project addons overriding user addons and bundled addons
    assert len(addons) == 6  # 3 project/user, 3 bundled

    # AND the list is sorted by name
    assert addons[0].name == "a-addon"
    assert addons[0].path == user_addon_a_path.resolve()
    assert addons[0].help_text == "User A help"
    assert addons[0].source == "user"

    assert addons[1].name == "collision-addon"
    assert addons[1].path == collision_addon_path.resolve()
    assert addons[1].help_text == "Project collision help"  # Project wins
    assert addons[1].source == "project"

    assert addons[2].name == "commit"
    assert addons[2].help_text == "Bundled commit help"
    assert addons[2].source == "bundled"

    assert addons[3].name == "manage-context"
    assert addons[3].help_text == "Bundled manage-context help"
    assert addons[3].source == "bundled"

    assert addons[4].name == "summarize"
    assert addons[4].help_text == "Bundled summarize help"
    assert addons[4].source == "bundled"

    assert addons[5].name == "z-addon"
    assert addons[5].path == project_addon_z_path.resolve()
    assert addons[5].help_text == "Project Z help"
    assert addons[5].source == "project"
