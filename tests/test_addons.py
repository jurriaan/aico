# pyright: standard
from pathlib import Path

import pytest
import typer
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.addons import create_click_command, discover_addons, execute_addon
from aico.consts import SESSION_FILE_NAME
from aico.exceptions import AddonExecutionError
from aico.models import AddonInfo, SessionData
from tests.helpers import save_session

runner = CliRunner()


def _create_addon(dir_path: Path, name: str, help_text: str) -> Path:
    addon_path = dir_path / name
    # Addon script must handle --usage and be executable
    addon_path.write_text(f'#!/bin/sh\n[ "$1" = "--usage" ] && echo "{help_text}" || exit 0')
    addon_path.chmod(0o755)
    return addon_path


def test_create_addon_command_execution(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an addon info and mocked execute_addon
    addon_path = tmp_path / "addon2"
    addon_info = AddonInfo(name="addon2", path=addon_path, help_text="Addon 2", source="project")
    mock_execute = mocker.patch("aico.addons.execute_addon")

    # WHEN creating a command from the addon info
    cmd = create_click_command(addon_info)

    # AND invoking it directly
    from click.testing import CliRunner as ClickRunner

    result = ClickRunner().invoke(cmd, ["arg1", "--flag"])

    # THEN the command invocation succeeds
    assert result.exit_code == 0

    # AND `execute_addon` was called with the correct AddonInfo
    mock_execute.assert_called_once_with(addon_info, ["arg1", "--flag"])


def test_alias_group_prioritizes_builtin(tmp_path: Path, mocker: MockerFixture) -> None:
    from aico.main import AliasGroup

    # GIVEN a Typer app using AliasGroup with a built-in command
    app = typer.Typer(cls=AliasGroup)

    @app.command(name="init")
    def _init() -> None:
        """A built-in command."""
        print("built-in init called")

    @app.command(name="secondary")
    def secondary() -> None:
        """A built-in command."""
        print("built-in secondary called")

    # AND an addon with the same name as the built-in
    addon_info = AddonInfo(name="init", path=tmp_path / "init", help_text="addon init help", source="project")
    mocker.patch("aico.addons.discover_addons", return_value=[addon_info])
    mock_execute = mocker.patch("aico.addons.execute_addon")

    # WHEN the command is invoked
    result = runner.invoke(app, ["init"])
    print(result.stdout)
    print(result.stderr)

    # THEN the built-in function was called, not the addon
    assert result.exit_code == 0
    assert "built-in init called" in result.stdout
    mock_execute.assert_not_called()

    # AND the help text shows the built-in command, not the addon
    help_result = runner.invoke(app, ["--help"])
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

    # AND a session file exists
    session_file = tmp_path / SESSION_FILE_NAME
    mocker.patch("aico.addons.find_session_file", return_value=session_file)

    # AND os.execvpe is mocked to raise an OSError
    mocker.patch("os.execvpe", side_effect=OSError("Test error"))

    # WHEN execute_addon is called
    # THEN it should raise AddonExecutionError wrapping the original error
    with pytest.raises(AddonExecutionError, match="Error executing addon 'my-addon': Test error"):
        execute_addon(addon_info, [])


def test_discover_addons(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a project addon and a user addon (with one name collision)
    session_file = tmp_path / SESSION_FILE_NAME
    save_session(session_file, SessionData(model="test", chat_history=[], context_files=[]))
    mocker.patch("aico.addons.find_session_file", return_value=session_file)

    # Trust the project so addons are discovered
    mocker.patch("aico.addons.is_project_trusted", return_value=True)

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

    # Since pathlib.Path implements the Traversable protocol, we can just return
    # the path to the temp directory we created.
    mocker.patch("importlib.resources.files", return_value=mock_bundled_resources_path)

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


def test_discover_addons_untrusted_skips_project(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN project addons exist
    session_file = tmp_path / SESSION_FILE_NAME
    save_session(session_file, SessionData(model="test", chat_history=[], context_files=[]))
    mocker.patch("aico.addons.find_session_file", return_value=session_file)

    # Mock home to avoid interference
    user_home_dir = tmp_path / "user_home"
    user_home_dir.mkdir()
    mocker.patch("pathlib.Path.home", return_value=user_home_dir)

    project_addons_dir = tmp_path / ".aico" / "addons"
    project_addons_dir.mkdir(parents=True)
    _create_addon(project_addons_dir, "malicious-addon", "Help text")

    # AND project is NOT trusted
    mocker.patch("aico.addons.is_project_trusted", return_value=False)

    # BUT bundled/user logic proceeds naturally (mock bundled empty to simplify)
    mocker.patch("importlib.resources.files", side_effect=Exception("No bundled"))

    # WHEN discovering
    addons = discover_addons()

    # THEN project addons are not returned
    assert not any(a.name == "malicious-addon" for a in addons)
