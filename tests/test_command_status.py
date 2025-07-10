# pyright: standard

from pathlib import Path

from typer.testing import CliRunner

from aico.main import app
from aico.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME, save_session

runner = CliRunner()


def test_status_shows_summary_with_excluded_and_start_index(tmp_path: Path) -> None:
    # GIVEN a session with 3 pairs, start index at 2 (msg index), and one pair excluded after the start index
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = [
            UserChatMessage(role="user", content="msg 0", mode=Mode.CONVERSATION, timestamp="t0"),  # pair 0
            AssistantChatMessage(
                role="assistant", content="resp 0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1
            ),
            UserChatMessage(role="user", content="msg 1", mode=Mode.CONVERSATION, timestamp="t1"),  # pair 1
            AssistantChatMessage(
                role="assistant", content="resp 1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1
            ),
            UserChatMessage(
                role="user", content="msg 2", mode=Mode.CONVERSATION, timestamp="t2", is_excluded=True
            ),  # pair 2
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
        # Active context starts at Pair 1 (user message index 2)
        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_index=2)
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and shows the correct summary
        assert result.exit_code == 0
        output = result.stdout
        assert "Total message pairs: 3" in output
        assert "Total excluded pairs: 1" in output
        assert "Active window: IDs 1-2 (2 pairs)" in output
        assert "Context to be sent: 1 of 2 active pairs (1 are excluded via `aico undo`)" in output


def test_status_shows_summary_with_no_excluded_messages(tmp_path: Path) -> None:
    # GIVEN a session with 2 pairs, none excluded, start index at 0
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

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and shows the correct summary
        assert result.exit_code == 0
        output = result.stdout
        assert "Total message pairs: 2" in output
        assert "Total excluded pairs" not in output
        assert "Active window: IDs 0-1 (2 pairs)" in output
        assert "Context to be sent: 2 of 2 active pairs" in output
        assert "(are excluded)" not in output


def test_status_handles_dangling_messages(tmp_path: Path) -> None:
    # GIVEN a session with a dangling user message in the active context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = [
            UserChatMessage(role="user", content="msg 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(
                role="assistant",
                content="resp 0",
                mode=Mode.CONVERSATION,
                timestamp="t0",
                model="m",
                duration_ms=1,
            ),
            UserChatMessage(role="user", content="dangling", mode=Mode.CONVERSATION, timestamp="t1"),
        ]
        # Set start index to after the first pair
        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_index=2)
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and reports the dangling message
        assert result.exit_code == 0
        output = result.stdout
        assert "Total message pairs: 1" in output
        assert "Context to be sent: 1 partial or dangling messages" in output


def test_status_fails_without_session(tmp_path: Path) -> None:
    # GIVEN an empty directory with no session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert f"Error: No session file '{SESSION_FILE_NAME}' found." in result.stderr
