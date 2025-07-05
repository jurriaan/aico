# pyright: standard

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.main import app
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from aico.utils import (
    SESSION_FILE_NAME,
    SessionDataAdapter,
    get_active_history,
    save_session,
)

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
                    timestamp=datetime.now(UTC).isoformat(),
                )
                for i in range(10)
            ],
            context_files=[],
        )
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico history set -2` is run
        # This tests the fix for command-line parsers interpreting "-2" as an option.
        result = runner.invoke(app, ["history", "set", "-2"])

        # THEN the command succeeds and reports the correct new index
        assert result.exit_code == 0
        assert "History start index set to 8" in result.stdout

        # AND the number of active messages for the next prompt is now 2
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        active_history = get_active_history(updated_session_data)
        assert len(active_history) == 2


def test_history_view_shows_summary_with_excluded_and_start_index(tmp_path: Path) -> None:
    # GIVEN a session with 6 messages, start index at 2, and one pair excluded after the start index
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = [
            UserChatMessage(role="user", content="msg 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(
                role="assistant", content="resp 0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1
            ),
            UserChatMessage(role="user", content="msg 1", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(
                role="assistant", content="resp 1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1
            ),
            UserChatMessage(role="user", content="msg 2", mode=Mode.CONVERSATION, timestamp="t2", is_excluded=True),
            AssistantChatMessage(
                role="assistant",
                content="resp 2",
                mode=Mode.CONVERSATION,
                timestamp="t2",
                model="m",
                duration_ms=1,
                is_excluded=True,
            ),
        ]
        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_index=2)
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN `aico history view` is run with color enabled for rich
        result = runner.invoke(app, ["history", "view"], color=True)

        # THEN the command succeeds and shows the correct summary
        assert result.exit_code == 0
        output = result.stdout
        # Test for key components rather than exact ANSI code-filled string
        assert "Full history summary:" in output
        assert "Total messages: 6 recorded." in output
        assert "Total excluded: 2 (across the entire history)." in output
        assert "Current context (for next prompt):" in output
        assert "Messages to be sent: 2" in output
        assert "(From an active window of 4 messages (indices 2-5), with 2 excluded via `aico undo`)" in output.replace(
            "\n", ""
        )


def test_history_view_shows_summary_with_no_excluded_messages(tmp_path: Path) -> None:
    # GIVEN a session with 4 messages, none excluded, start index at 0
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = [
            UserChatMessage(role="user", content="msg 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(
                role="assistant", content="resp 0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1
            ),
            UserChatMessage(role="user", content="msg 1", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(
                role="assistant", content="resp 1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1
            ),
        ]
        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_index=0)
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN `aico history view` is run with color enabled for rich
        result = runner.invoke(app, ["history", "view"], color=True)

        # THEN the command succeeds and shows the correct summary
        assert result.exit_code == 0
        output = result.stdout
        assert "Full history summary:" in output
        assert "Total messages: 4 recorded." in output
        assert "Total excluded: 0 (across the entire history)." in output
        assert "Current context (for next prompt):" in output
        assert "Messages to be sent: 4" in output
        assert "(From an active window of 4 messages (indices 0-3), with 0 excluded via `aico undo`)" in output.replace(
            "\n", ""
        )


def test_history_reset_sets_index_to_zero(tmp_path: Path) -> None:
    # GIVEN a session with 10 messages and the history index at 5
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        chat_history: list[ChatMessageHistoryItem] = [
            UserChatMessage(
                role="user",
                content=f"msg {i}",
                mode=Mode.CONVERSATION,
                timestamp=datetime.now(UTC).isoformat(),
            )
            for i in range(10)
        ]
        session_data = SessionData(
            model="test-model",
            context_files=[],
            chat_history=chat_history,
            history_start_index=5,
        )
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico history reset` is run
        result = runner.invoke(app, ["history", "reset"])

        # THEN the command succeeds and reports the reset
        assert result.exit_code == 0
        assert "History index reset to 0. Full chat history is now active." in result.stdout

        # AND all 10 messages are now active for the next prompt
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        active_history = get_active_history(updated_session_data)
        assert len(active_history) == 10


def test_history_set_with_positive_index(tmp_path: Path) -> None:
    # GIVEN a session with 10 history messages
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_data = SessionData(
            model="test-model",
            context_files=[],
            chat_history=[
                UserChatMessage(
                    role="user",
                    content=f"msg {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=datetime.now(UTC).isoformat(),
                )
                for i in range(10)
            ],
        )
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico history set 7` is run
        result = runner.invoke(app, ["history", "set", "7"])

        # THEN the command succeeds and reports the new index
        assert result.exit_code == 0
        assert "History start index set to 7" in result.stdout

        # AND the number of active messages for the next prompt is now 3
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        active_history = get_active_history(updated_session_data)
        assert len(active_history) == 3


@pytest.mark.parametrize(
    "invalid_input,error_message",
    [
        ("11", "Error: Index out of bounds"),
        ("-11", "Error: Index out of bounds"),
        ("abc", "Error: Invalid index 'abc'"),
    ],
)
def test_history_set_fails_with_invalid_index(tmp_path: Path, invalid_input: str, error_message: str) -> None:
    # GIVEN a session with 10 history messages and a non-zero start index
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_data = SessionData(
            model="test-model",
            context_files=[],
            chat_history=[
                UserChatMessage(
                    role="user",
                    content=f"msg {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=datetime.now(UTC).isoformat(),
                )
                for i in range(10)
            ],
            history_start_index=5,
        )
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # AND the initial number of active messages is 5
        initial_active_history = get_active_history(session_data)
        assert len(initial_active_history) == 5

        # WHEN `aico history set` is run with an invalid index
        result = runner.invoke(app, ["history", "set", invalid_input])

        # THEN the command fails with a specific error
        assert result.exit_code == 1
        assert error_message in result.stderr

        # AND the number of active messages remains unchanged
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        final_active_history = get_active_history(updated_session_data)
        assert len(final_active_history) == 5


@pytest.mark.parametrize(
    "command_args",
    [
        ["history", "view"],
        ["history", "reset"],
        ["history", "set", "5"],
    ],
)
def test_history_commands_fail_without_session(tmp_path: Path, command_args: list[str]) -> None:
    # GIVEN an empty directory with no session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # WHEN a history command is run
        result = runner.invoke(app, command_args)

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert f"Error: No session file '{SESSION_FILE_NAME}' found." in result.stderr
