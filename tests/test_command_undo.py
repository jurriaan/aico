# pyright: standard
from dataclasses import replace
from pathlib import Path

from typer.testing import CliRunner

from aico.main import app
from aico.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
from aico.utils import (
    SESSION_FILE_NAME,
    SessionDataAdapter,
    get_active_history,
    save_session,
)

runner = CliRunner()


def _create_history(count: int) -> list[UserChatMessage | AssistantChatMessage]:
    history = []
    for i in range(count // 2):
        history.append(
            UserChatMessage(
                role="user",
                content=f"user prompt {i}",
                mode=Mode.CONVERSATION,
                timestamp=f"ts{i}",
            )
        )
        history.append(
            AssistantChatMessage(
                role="assistant",
                content=f"assistant response {i}",
                mode=Mode.CONVERSATION,
                timestamp=f"ts{i}",
                model="test-model",
                duration_ms=100,
            )
        )
    return history


def _setup_session(tmp_path: Path, history_size: int) -> Path:
    session_file = tmp_path / SESSION_FILE_NAME
    history = _create_history(history_size)
    session_data = SessionData(model="test", context_files=[], chat_history=history)
    save_session(session_file, session_data)
    return session_file


def _load_session_data(session_file: Path) -> SessionData:
    return SessionDataAdapter.validate_json(session_file.read_text())


def test_undo_default_one_pair(tmp_path: Path) -> None:
    # GIVEN a session with 4 messages (2 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = _setup_session(Path(td), 4)

        # AND initially all 4 messages are active
        initial_session_data = _load_session_data(session_file)
        assert len(get_active_history(initial_session_data)) == 4

        # WHEN `aico undo` is run with default count
        result = runner.invoke(app, ["undo"])

        # THEN the command succeeds and prints a confirmation
        assert result.exit_code == 0
        assert "Marked the last 2 messages as excluded." in result.stdout

        # AND the number of active messages is now 2
        final_session = _load_session_data(session_file)
        assert len(get_active_history(final_session)) == 2
        # AND the last two messages are marked as excluded
        assert final_session.chat_history[0].is_excluded is False
        assert final_session.chat_history[1].is_excluded is False
        assert final_session.chat_history[2].is_excluded is True
        assert final_session.chat_history[3].is_excluded is True


def test_undo_count_two_pairs(tmp_path: Path) -> None:
    # GIVEN a session with 4 messages (2 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = _setup_session(Path(td), 4)

        # AND initially all 4 messages are active
        initial_session_data = _load_session_data(session_file)
        assert len(get_active_history(initial_session_data)) == 4

        # WHEN `aico undo 2` is run
        result = runner.invoke(app, ["undo", "2"])

        # THEN the command succeeds and prints a confirmation for 4 messages
        assert result.exit_code == 0
        assert "Marked the last 4 messages as excluded." in result.stdout

        # AND the number of active messages is now 0
        final_session = _load_session_data(session_file)
        assert len(get_active_history(final_session)) == 0
        # AND all messages are marked as excluded
        assert all(msg.is_excluded for msg in final_session.chat_history)


def test_undo_on_empty_history(tmp_path: Path) -> None:
    # GIVEN a session with an empty history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _setup_session(Path(td), 0)

        # WHEN `aico undo` is run
        result = runner.invoke(app, ["undo"])

        # THEN the command exits gracefully with a message
        assert result.exit_code == 1
        assert "Error: Cannot undo, chat history is empty." in result.stderr


def test_undo_count_exceeds_history(tmp_path: Path) -> None:
    # GIVEN a session with 4 messages (2 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = _setup_session(Path(td), 4)
        initial_session_data = _load_session_data(session_file)
        assert len(get_active_history(initial_session_data)) == 4

        # WHEN `aico undo` is run with a count that exceeds the history length
        result = runner.invoke(app, ["undo", "3"])  # 3 pairs = 6 messages

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert "Error: Cannot undo 3 pairs (6 messages), history only contains 4 messages." in result.stderr

        # AND the number of active messages remains unchanged
        final_session = _load_session_data(session_file)
        assert len(get_active_history(final_session)) == 4
        # AND no messages were changed
        assert all(not msg.is_excluded for msg in final_session.chat_history)


def test_undo_on_already_excluded_messages(tmp_path: Path) -> None:
    # GIVEN a session where the last pair is already excluded
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = _setup_session(Path(td), 4)
        session_data = _load_session_data(session_file)

        # Manually exclude the last two messages
        session_data.chat_history[2] = replace(session_data.chat_history[2], is_excluded=True)
        session_data.chat_history[3] = replace(session_data.chat_history[3], is_excluded=True)
        save_session(session_file, session_data)

        # AND there are initially 2 active messages
        assert len(get_active_history(session_data)) == 2

        # WHEN `aico undo` is run again
        result = runner.invoke(app, ["undo"])

        # THEN the command succeeds and marks the NEXT available pair as excluded
        assert result.exit_code == 0
        assert "Marked the last 2 messages as excluded." in result.stdout

        # AND there are now 0 active messages
        final_session = _load_session_data(session_file)
        assert len(get_active_history(final_session)) == 0
        # AND all four messages are now excluded
        assert all(msg.is_excluded for msg in final_session.chat_history)
