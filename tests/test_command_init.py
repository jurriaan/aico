# pyright: standard

import json
from pathlib import Path

from typer.testing import CliRunner

from aico.consts import SESSION_FILE_NAME
from aico.main import app

runner = CliRunner()


def test_init_creates_session_file_in_empty_dir(tmp_path: Path) -> None:
    # GIVEN a directory without a session file
    # We use pytest's tmp_path fixture and run the command within that isolated directory.
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # WHEN `aico init` is run
        result = runner.invoke(app, ["init"])

        # THEN the command succeeds and creates the session file
        assert result.exit_code == 0
        pointer_file = Path(td) / SESSION_FILE_NAME
        assert pointer_file.is_file()
        assert f"Initialized session file: {pointer_file.name}" in result.stdout

        # AND the pointer file has the correct format and points to a view
        pointer_data = json.loads(pointer_file.read_text())
        assert pointer_data["type"] == "aico_session_pointer_v1"
        view_path = Path(td) / pointer_data["path"]
        assert view_path.is_file()

        # AND the view file contains the default model
        view_data = json.loads(view_path.read_text())
        assert view_data["model"] == "openrouter/google/gemini-3-pro-preview"


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


def test_init_creates_gitignore(tmp_path: Path) -> None:
    # GIVEN an empty project directory
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # WHEN `aico init` is run
        result = runner.invoke(app, ["init", "--model", "test-model"])
        assert result.exit_code == 0

        # THEN the .aico/.gitignore file is created with the correct content
        gitignore_path = Path(td) / ".aico" / ".gitignore"
        assert gitignore_path.is_file()
        assert gitignore_path.read_text() == "*\n!addons/\n!.gitignore\n"


def test_init_creates_secure_directories(tmp_path: Path) -> None:
    """Tests that init creates .aico directories with secure 0700 permissions."""

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        result = runner.invoke(app, ["init", "--model", "test-model"])
        assert result.exit_code == 0

        aico_dir = Path(td) / ".aico"
        history_dir = aico_dir / "history"
        sessions_dir = aico_dir / "sessions"

        for dir_path in [aico_dir, history_dir, sessions_dir]:
            assert dir_path.is_dir()
            mode = dir_path.stat().st_mode & 0o777
            assert mode == 0o700, f"Expected 0700 for {dir_path}, got {oct(mode)}"
