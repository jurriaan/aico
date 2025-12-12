# pyright: standard
from pathlib import Path

from typer.testing import CliRunner

from aico.historystore import HistoryStore, load_view
from aico.historystore.models import HistoryRecord
from aico.lib.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from aico.main import app
from tests.helpers import init_shared_session

runner = CliRunner()


def test_history_splice_inserts_correctly(tmp_path: Path) -> None:
    # GIVEN a shared session with 2 pairs
    history: list[ChatMessageHistoryItem] = [
        # Pair 0
        UserChatMessage(role="user", content="u0", mode=Mode.CONVERSATION, timestamp="t0"),
        AssistantChatMessage(
            role="assistant",
            content="a0",
            mode=Mode.CONVERSATION,
            timestamp="t0",
            model="m",
            duration_ms=1,
        ),
        # Pair 1
        UserChatMessage(role="user", content="u1", mode=Mode.CONVERSATION, timestamp="t1"),
        AssistantChatMessage(
            role="assistant",
            content="a1",
            mode=Mode.CONVERSATION,
            timestamp="t1",
            model="m",
            duration_ms=1,
        ),
    ]
    session_data = SessionData(
        model="test",
        chat_history=history,
    )
    init_shared_session(tmp_path, session_data)

    # Add a new record manually to splice in
    history_root = tmp_path / ".aico" / "history"
    store = HistoryStore(history_root)

    new_asst_rec = HistoryRecord(
        role="assistant",
        content="new_a",
        mode=Mode.CONVERSATION,
        timestamp="now",
        model="m",
        duration_ms=1,
    )
    new_asst_id = store.append(new_asst_rec)  # Should be ID 4 (0,1,2,3 exist)

    # Reuse User ID 0

    # WHEN inserting at index 1 (between pair 0 and pair 1)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["history-splice", "0", str(new_asst_id), "--at-index", "1"])

    # THEN success
    assert result.exit_code == 0, result.stderr

    # AND view is updated
    view_path = tmp_path / ".aico" / "sessions" / "main.json"
    view = load_view(view_path)

    # Expected indices:
    # Pair 0: [0, 1]
    # New Pair: [0, 4]
    # Old Pair 1: [2, 3]
    # Total sequence: 0, 1, 0, 4, 2, 3
    assert view.message_indices == [0, 1, 0, 4, 2, 3]


def test_history_splice_fails_invalid_index(tmp_path: Path) -> None:
    # GIVEN session with 1 pair
    init_shared_session(
        tmp_path,
        SessionData(
            model="m",
            chat_history=[
                UserChatMessage(role="user", content="u", mode=Mode.CONVERSATION, timestamp="ts"),
                AssistantChatMessage(
                    role="assistant",
                    content="a",
                    mode=Mode.CONVERSATION,
                    timestamp="ts",
                    model="m",
                    duration_ms=0,
                ),
            ],
        ),
    )

    # Get arbitrary valid IDs
    u_id = 0
    a_id = 1

    # WHEN splicing at index 5 (out of bounds)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["history-splice", str(u_id), str(a_id), "--at-index", "5"])

    # THEN fails
    assert result.exit_code == 1
    assert "Insertion index 5 is out of bounds" in result.stderr


def test_history_splice_fails_invalid_ids(tmp_path: Path) -> None:
    init_shared_session(tmp_path, SessionData(model="m", chat_history=[]))

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["history-splice", "999", "888", "--at-index", "0"])

    assert result.exit_code == 1
    assert "User message ID 999 not found" in result.stderr
