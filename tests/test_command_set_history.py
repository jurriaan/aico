# pyright: standard

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.consts import SESSION_FILE_NAME
from aico.historystore import (
    HistoryStore,
    SessionView,
    append_pair_to_view,
    load_view,
    save_view,
    switch_active_pointer,
)
from aico.historystore.models import HistoryRecord
from aico.main import app
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from aico.session import build_active_context
from tests.helpers import load_session_data, save_session

runner = CliRunner()


def test_set_history_with_negative_index_argument(tmp_path: Path) -> None:
    # GIVEN a session with 10 history messages (5 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(5):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico set-history -2` is run
        result = runner.invoke(app, ["set-history", "-2"])

        # THEN the command succeeds and reports starting at pair -2
        # The resolved index of -2 in a 5-pair list is 3.
        assert result.exit_code == 0
        assert "History context will now start at pair 3." in result.stdout

        # AND the history start pair is set to index 3
        updated_session_data = load_session_data(session_file)
        assert updated_session_data.history_start_pair == 3


def test_set_history_with_positive_pair_index(tmp_path: Path) -> None:
    # GIVEN a session with 6 history messages (3 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(3):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico set-history 1` is run
        result = runner.invoke(app, ["set-history", "1"])

        # THEN the command succeeds and reports starting at pair 1
        assert result.exit_code == 0
        assert "History context will now start at pair 1." in result.stdout

        # AND the history start pair is set to index 1
        updated_session_data = load_session_data(session_file)
        assert updated_session_data.history_start_pair == 1


def test_set_history_to_clear_context(tmp_path: Path) -> None:
    # GIVEN a session with 4 history messages (2 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(2):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico set-history 2` is run (where 2 is num_pairs)
        result = runner.invoke(app, ["set-history", "2"])

        # THEN the command succeeds and confirms the context is cleared
        assert result.exit_code == 0
        assert "History context cleared (will start after the last conversation)." in result.stdout

        # AND the history start pair is set to 2 (num_pairs)
        updated_session_data = load_session_data(session_file)
        assert updated_session_data.history_start_pair == 2


@pytest.mark.parametrize(
    "invalid_input,error_message",
    [
        (
            "4",  # For 3 pairs, index 3 is valid (clear context), so 4 is the first invalid positive index.
            "Error: Index out of bounds. Valid indices are in the range 0 to 2 (or -1 to -3), or 3 to clear context.",
        ),
        (
            "-4",  # For 3 pairs, -3 is the first valid negative index, so -4 is the first invalid one.
            "Error: Index out of bounds. Valid indices are in the range 0 to 2 (or -1 to -3), or 3 to clear context.",
        ),
        ("abc", "Error: Invalid index 'abc'"),
    ],
)
def test_set_history_fails_with_invalid_index(tmp_path: Path, invalid_input: str, error_message: str) -> None:
    # GIVEN a session with 6 history messages (3 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(3):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_pair=1)
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)
        original_start_pair = session_data.history_start_pair

        # WHEN `aico set-history` is run with an invalid index
        result = runner.invoke(app, ["set-history", invalid_input])

        # THEN the command fails with a specific error
        assert result.exit_code == 1
        assert error_message in result.stderr

        # AND the history start pair remains unchanged
        updated_session_data = load_session_data(session_file)
        assert updated_session_data.history_start_pair == original_start_pair


def test_set_history_fails_without_session(tmp_path: Path) -> None:
    # GIVEN an empty directory with no session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # WHEN `aico set-history` is run
        result = runner.invoke(app, ["set-history", "5"])

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert f"Error: No session file '{SESSION_FILE_NAME}' found." in result.stderr


def test_set_history_with_zero_sets_index_to_zero(tmp_path: Path) -> None:
    # GIVEN a session with 10 messages (5 pairs) and the history index at 4
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(5):
            history.append(
                UserChatMessage(
                    role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=datetime.now(UTC).isoformat()
                )
            )
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=datetime.now(UTC).isoformat(),
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(
            model="test-model",
            context_files=[],
            chat_history=history,
            history_start_pair=2,  # Start at pair 2 to test reset
        )
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico set-history 0` is run (replacing `history reset`)
        result = runner.invoke(app, ["set-history", "0"])

        # THEN the command succeeds and reports the reset
        assert result.exit_code == 0
        assert "History context reset. Full chat history is now active." in result.stdout

        # AND the history start pair is now 0
        updated_session_data = load_session_data(session_file)
        assert updated_session_data.history_start_pair == 0
        context = build_active_context(updated_session_data)
        active_history = context["active_history"]
        assert len(active_history) == 10


def test_set_history_with_clear_keyword(tmp_path: Path) -> None:
    # GIVEN a session with 4 history messages (2 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(2):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico set-history clear` is run
        result = runner.invoke(app, ["set-history", "clear"])

        # THEN the command succeeds and confirms the context is cleared
        assert result.exit_code == 0
        assert "History context cleared (will start after the last conversation)." in result.stdout

        # AND the history start pair is set to 2 (the total number of pairs)
        updated_session_data = load_session_data(session_file)
        assert updated_session_data.history_start_pair == 2


def test_set_history_can_move_pointer_backwards(tmp_path: Path) -> None:
    # GIVEN a legacy session with 3 pairs and history_start_pair at 2
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(3):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_pair=2)
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico set-history 0` is run
        result = runner.invoke(app, ["set-history", "0"])

        # THEN the command succeeds and reports success
        assert result.exit_code == 0
        assert "History context reset. Full chat history is now active." in result.stdout

        # AND the history start pair is set back to 0
        updated_session_data = load_session_data(session_file)
        assert updated_session_data.history_start_pair == 0


def test_set_history_can_move_pointer_backwards_shared_history(tmp_path: Path) -> None:
    # GIVEN a shared-history session with 3 pairs and history_start_pair at 2
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        project_root = Path(td)
        history_root = project_root / ".aico" / "history"
        sessions_dir = project_root / ".aico" / "sessions"
        history_root.mkdir(parents=True, exist_ok=True)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        store = HistoryStore(history_root)
        view = SessionView(
            model="test-model",
            context_files=[],
            message_indices=[],
            history_start_pair=2,
            excluded_pairs=[],
        )

        for i in range(3):
            user_record = HistoryRecord(
                role="user",
                content=f"p{i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
            )
            assistant_record = HistoryRecord(
                role="assistant",
                content=f"r{i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
                model="m",
                duration_ms=1,
            )
            _ = append_pair_to_view(store, view, user_record, assistant_record)

        view_path = sessions_dir / "main.json"
        save_view(view_path, view)
        session_file = project_root / SESSION_FILE_NAME
        switch_active_pointer(session_file, view_path)

        # WHEN `aico set-history 0` is run
        result = runner.invoke(app, ["set-history", "0"])

        # THEN the command succeeds and reports success
        assert result.exit_code == 0
        assert "History context reset. Full chat history is now active." in result.stdout

        # AND the history start pair is set back to 0 in the underlying view
        updated_view = load_view(view_path)
        assert updated_view.history_start_pair == 0


def test_set_history_clear_uses_full_history_in_shared_session(tmp_path: Path) -> None:
    # GIVEN a shared-history session with 3 pairs and an active window starting at pair 1
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        project_root = Path(td)
        history_root = project_root / ".aico" / "history"
        sessions_dir = project_root / ".aico" / "sessions"
        history_root.mkdir(parents=True, exist_ok=True)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        store = HistoryStore(history_root)
        view = SessionView(
            model="test-model",
            context_files=[],
            message_indices=[],
            history_start_pair=1,
            excluded_pairs=[],
        )

        for i in range(3):
            user_record = HistoryRecord(
                role="user",
                content=f"p{i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
            )
            assistant_record = HistoryRecord(
                role="assistant",
                content=f"r{i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
                model="m",
                duration_ms=1,
            )
            _ = append_pair_to_view(store, view, user_record, assistant_record)

        view_path = sessions_dir / "main.json"
        save_view(view_path, view)
        session_file = project_root / SESSION_FILE_NAME
        switch_active_pointer(session_file, view_path)

        # WHEN `aico set-history clear` is run
        result = runner.invoke(app, ["set-history", "clear"])

        # THEN the command succeeds and confirms the context is cleared
        assert result.exit_code == 0
        assert "History context cleared (will start after the last conversation)." in result.stdout

        # AND the history start pair is set to the total number of pairs in the full history (3)
        updated_view = load_view(view_path)
        assert updated_view.history_start_pair == 3


def test_set_history_fails_with_invalid_index_shared_history(tmp_path: Path) -> None:
    # GIVEN a shared-history session with 3 pairs and an active window starting at pair 1
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        project_root = Path(td)
        history_root = project_root / ".aico" / "history"
        sessions_dir = project_root / ".aico" / "sessions"
        history_root.mkdir(parents=True, exist_ok=True)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        store = HistoryStore(history_root)
        view = SessionView(
            model="test-model",
            context_files=[],
            message_indices=[],
            history_start_pair=1,
            excluded_pairs=[],
        )

        for i in range(3):
            user_record = HistoryRecord(
                role="user",
                content=f"p{i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
            )
            assistant_record = HistoryRecord(
                role="assistant",
                content=f"r{i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
                model="m",
                duration_ms=1,
            )
            _ = append_pair_to_view(store, view, user_record, assistant_record)

        view_path = sessions_dir / "main.json"
        save_view(view_path, view)
        session_file = project_root / SESSION_FILE_NAME
        switch_active_pointer(session_file, view_path)

        # WHEN `aico set-history` is run with an out-of-bounds index
        result = runner.invoke(app, ["set-history", "4"])

        # THEN the command fails with a clear error message using full-history bounds
        assert result.exit_code == 1
        assert (
            "Error: Index out of bounds. Valid indices are in the range 0 to 2 (or -1 to -3), or 3 to clear context."
            in result.stderr
        )

        # AND the underlying view's history_start_pair remains unchanged
        updated_view = load_view(view_path)
        assert updated_view.history_start_pair == 1
