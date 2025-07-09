# pyright: standard

from pathlib import Path

from typer.testing import CliRunner

from aico.main import app
from aico.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME, save_session

runner = CliRunner()


def test_status_shows_summary_with_excluded_and_start_index(tmp_path: Path) -> None:
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

        # WHEN `aico status` is run with color enabled for rich
        result = runner.invoke(app, ["status"], color=True)

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


def test_status_shows_summary_with_no_excluded_messages(tmp_path: Path) -> None:
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

        # WHEN `aico status` is run with color enabled for rich
        result = runner.invoke(app, ["status"], color=True)

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


def test_status_fails_without_session(tmp_path: Path) -> None:
    # GIVEN an empty directory with no session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert f"Error: No session file '{SESSION_FILE_NAME}' found." in result.stderr
