import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.main import app
from aico.models import Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def test_history_set_with_negative_index_argument(tmp_path: Path) -> None:
    # GIVEN a session with 10 history messages
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_data = SessionData(
            model="test-model",
            chat_history=[
                UserChatMessage(
                    role="user",
                    content=f"msg {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                for i in range(10)
            ],
        )
        session_file = Path(td) / SESSION_FILE_NAME
        session_file.write_text(session_data.model_dump_json())

        # WHEN `aico history set -2` is run
        # This tests the fix for command-line parsers interpreting "-2" as an option.
        result = runner.invoke(app, ["history", "set", "-2"])

        # THEN the command succeeds and reports the correct new index
        assert result.exit_code == 0
        assert "History start index set to 8" in result.stdout

        # AND the session file is updated with the correct index
        updated_session_data = json.loads(session_file.read_text())
        assert updated_session_data["history_start_index"] == 8


def test_history_view_shows_correct_status(tmp_path: Path) -> None:
    # GIVEN a session with 10 messages and the index at 4
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_data = SessionData(
            model="test-model",
            chat_history=[
                UserChatMessage(
                    role="user",
                    content=f"msg {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                for i in range(10)
            ],
            history_start_index=4,
        )
        (Path(td) / SESSION_FILE_NAME).write_text(session_data.model_dump_json())

        # WHEN `aico history view` is run
        result = runner.invoke(app, ["history", "view"])

        # THEN the command succeeds and shows the correct status
        assert result.exit_code == 0
        assert "Active history starts at index 4 of 10 total messages." in result.stdout
        assert (
            "(6 messages will be sent as context in the next prompt.)" in result.stdout
        )


def test_history_reset_sets_index_to_zero(tmp_path: Path) -> None:
    # GIVEN a session with the history index at 5
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_data = SessionData(
            model="test-model",
            chat_history=[
                UserChatMessage(
                    role="user",
                    content=f"msg {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                for i in range(10)
            ],
            history_start_index=5,
        )
        session_file = Path(td) / SESSION_FILE_NAME
        session_file.write_text(session_data.model_dump_json())

        # WHEN `aico history reset` is run
        result = runner.invoke(app, ["history", "reset"])

        # THEN the command succeeds and reports the reset
        assert result.exit_code == 0
        assert (
            "History index reset to 0. Full chat history is now active."
            in result.stdout
        )

        # AND the session file is updated
        updated_session_data = json.loads(session_file.read_text())
        assert updated_session_data["history_start_index"] == 0


def test_history_set_with_positive_index(tmp_path: Path) -> None:
    # GIVEN a session with 10 history messages
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_data = SessionData(
            model="test-model",
            chat_history=[
                UserChatMessage(
                    role="user",
                    content=f"msg {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                for i in range(10)
            ],
        )
        session_file = Path(td) / SESSION_FILE_NAME
        session_file.write_text(session_data.model_dump_json())

        # WHEN `aico history set 7` is run
        result = runner.invoke(app, ["history", "set", "7"])

        # THEN the command succeeds and reports the new index
        assert result.exit_code == 0
        assert "History start index set to 7" in result.stdout

        # AND the session file is updated
        updated_session_data = json.loads(session_file.read_text())
        assert updated_session_data["history_start_index"] == 7


@pytest.mark.parametrize(
    "invalid_input,error_message",
    [
        ("11", "Error: Index out of bounds"),
        ("-11", "Error: Index out of bounds"),
        ("abc", "Error: Invalid index 'abc'"),
    ],
)
def test_history_set_fails_with_invalid_index(
    tmp_path: Path, invalid_input: str, error_message: str
) -> None:
    # GIVEN a session with 10 history messages and a non-zero start index
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_data = SessionData(
            model="test-model",
            chat_history=[
                UserChatMessage(
                    role="user",
                    content=f"msg {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                for i in range(10)
            ],
            history_start_index=5,
        )
        session_file = Path(td) / SESSION_FILE_NAME
        session_file.write_text(session_data.model_dump_json())

        # WHEN `aico history set` is run with an invalid index
        result = runner.invoke(app, ["history", "set", invalid_input])

        # THEN the command fails with a specific error
        assert result.exit_code == 1
        assert error_message in result.stderr

        # AND the session file remains unchanged
        updated_session_data = json.loads(session_file.read_text())
        assert updated_session_data["history_start_index"] == 5


@pytest.mark.parametrize(
    "command_args",
    [
        ["history", "view"],
        ["history", "reset"],
        ["history", "set", "5"],
    ],
)
def test_history_commands_fail_without_session(
    tmp_path: Path, command_args: list[str]
) -> None:
    # GIVEN an empty directory with no session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # WHEN a history command is run
        result = runner.invoke(app, command_args)

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert f"Error: No session file '{SESSION_FILE_NAME}' found." in result.stderr
