# pyright: standard

from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.main import app
from aico.models import SessionData
from aico.utils import SESSION_FILE_NAME, save_session

runner = CliRunner()


def test_aico_session_file_env_var_works(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session file at a non-standard location
    session_dir = tmp_path / "custom" / "location"
    session_dir.mkdir(parents=True)
    session_file = session_dir / SESSION_FILE_NAME
    save_session(session_file, SessionData(model="test-model"))
    
    # WHEN AICO_SESSION_FILE is set to that absolute path
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": str(session_file.resolve())})
        
        # AND we run aico history view (which needs to find the session file)
        result = runner.invoke(app, ["history", "view"])
        
        # THEN the command succeeds and uses the session file from the env var
        assert result.exit_code == 0
        assert "Active history starts" in result.stdout


def test_aico_session_file_env_var_fails_for_relative_path(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a relative path in AICO_SESSION_FILE
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": "relative/path.json"})
        
        # WHEN we run aico history view
        result = runner.invoke(app, ["history", "view"])
        
        # THEN the command fails with a clear error
        assert result.exit_code == 1
        assert "AICO_SESSION_FILE must be an absolute path" in result.stderr


def test_aico_session_file_env_var_fails_for_nonexistent_file(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an absolute path to a non-existent file in AICO_SESSION_FILE
    nonexistent_file = tmp_path / "does_not_exist.json"
    
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": str(nonexistent_file.resolve())})
        
        # WHEN we run aico history view
        result = runner.invoke(app, ["history", "view"])
        
        # THEN the command fails with a clear error
        assert result.exit_code == 1
        assert "Session file specified in AICO_SESSION_FILE does not exist" in result.stderr


def test_aico_session_file_env_var_not_set_uses_upward_search(tmp_path: Path) -> None:
    # GIVEN a session file in the current directory (normal case)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, SessionData(model="upward-search-model"))
        
        # AND AICO_SESSION_FILE is not set
        # WHEN we run aico history view
        result = runner.invoke(app, ["history", "view"])
        
        # THEN the command succeeds and finds the session file via upward search
        assert result.exit_code == 0
        assert "Active history starts" in result.stdout
