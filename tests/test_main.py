# pyright: standard

from pathlib import Path

from typer.testing import CliRunner

from aico.main import app
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def test_no_command_shows_help() -> None:
    # GIVEN the app
    # WHEN `aico` is run with no command
    result = runner.invoke(app, [])

    # THEN the command succeeds and shows the help text
    assert result.exit_code == 0
    assert "Usage: root [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert " init" in result.stdout
    assert " add" in result.stdout
    assert " last" in result.stdout
    assert " drop" in result.stdout
    assert " prompt" in result.stdout


def test_init_creates_session_file_in_empty_dir(tmp_path: Path) -> None:
    # GIVEN a directory without a session file
    # We use pytest's tmp_path fixture and run the command within that isolated directory.
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # WHEN `aico init` is run
        result = runner.invoke(app, ["init"])

        # THEN the command succeeds and creates the session file
        assert result.exit_code == 0
        session_file = Path(td) / SESSION_FILE_NAME
        assert session_file.is_file()
        assert f"Initialized session file: {session_file}" in result.stdout

        # AND the session file contains the default model
        assert '"model": "openrouter/google/gemini-2.5-pro"' in session_file.read_text()


def test_init_fails_if_session_already_exists(tmp_path: Path) -> None:
    # GIVEN a directory with an existing session file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        expected_path = Path(td) / SESSION_FILE_NAME
        expected_path.touch()

        # WHEN `aico init` is run again
        result = runner.invoke(app, ["init"])

        # THEN the command fails with an appropriate error message
        assert result.exit_code == 1

        assert f"Error: Session file '{expected_path}' already exists in this directory." in result.stderr
