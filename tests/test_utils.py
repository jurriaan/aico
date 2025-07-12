# pyright: standard

from pathlib import Path

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
    save_session(session_file, SessionData(model="test-model", context_files=[], chat_history=[]))

    # AND litellm dependencies are mocked
    mocker.patch("aico.commands.status._count_tokens", return_value=10)
    mocker.patch("litellm.get_model_info", return_value=None)

    # WHEN AICO_SESSION_FILE is set to that absolute path
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": str(session_file.resolve())})

        # AND we run aico status (which needs to find the session file)
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and uses the session file from the env var
        assert result.exit_code == 0
        assert "test-model" in result.stdout


def test_aico_session_file_env_var_fails_for_relative_path(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a relative path in AICO_SESSION_FILE
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": "relative/path.json"})

        # WHEN we run aico status
        result = runner.invoke(app, ["status"])

        # THEN the command fails with a clear error
        assert result.exit_code == 1
        assert "AICO_SESSION_FILE must be an absolute path" in result.stderr


def test_aico_session_file_env_var_fails_for_nonexistent_file(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an absolute path to a non-existent file in AICO_SESSION_FILE
    nonexistent_file = tmp_path / "does_not_exist.json"

    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": str(nonexistent_file.resolve())})

        # WHEN we run aico status
        result = runner.invoke(app, ["status"])

        # THEN the command fails with a clear error
        assert result.exit_code == 1
        assert "Session file specified in AICO_SESSION_FILE does not exist" in result.stderr


def test_aico_session_file_env_var_not_set_uses_upward_search(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session file in the current directory (normal case)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, SessionData(model="upward-search-model", context_files=[], chat_history=[]))

        # AND litellm dependencies are mocked
        mocker.patch("aico.commands.status._count_tokens", return_value=10)
        mocker.patch("litellm.get_model_info", return_value=None)

        # AND AICO_SESSION_FILE is not set
        # WHEN we run aico status
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and finds the session file via upward search
        assert result.exit_code == 0
        assert "upward-search-model" in result.stdout


def test_get_active_history_filters_and_slices() -> None:
    # GIVEN a SessionData object with a mix of messages
    from aico.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
    from aico.utils import get_active_history

    history = [
        UserChatMessage(role="user", content="msg 0 - before start", mode=Mode.RAW, timestamp="t0"),  # before start
        UserChatMessage(role="user", content="msg 1 - active", mode=Mode.RAW, timestamp="t1"),  # after start
        UserChatMessage(
            role="user", content="msg 2 - excluded", mode=Mode.RAW, timestamp="t2", is_excluded=True
        ),  # after start, excluded
        AssistantChatMessage(
            role="assistant",
            content="resp 2 - excluded",
            mode=Mode.RAW,
            timestamp="t3",
            model="m",
            duration_ms=1,
            is_excluded=True,
        ),
        UserChatMessage(role="user", content="msg 3 - active", mode=Mode.RAW, timestamp="t4"),  # after start
    ]
    session_data = SessionData(
        model="test",
        context_files=[],
        chat_history=history,
        history_start_index=1,
    )

    # WHEN get_active_history is called
    active_history = get_active_history(session_data)

    # THEN the returned list contains only the correct messages
    assert len(active_history) == 2
    assert active_history[0].content == "msg 1 - active"
    assert active_history[1].content == "msg 3 - active"
