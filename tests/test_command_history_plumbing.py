# pyright: standard
from pathlib import Path

from typer.testing import CliRunner

from aico.historystore import HistoryStore, load_view
from aico.historystore.models import HistoryRecord
from aico.historystore.session_view import save_view
from aico.main import app
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from tests.helpers import init_shared_session

runner = CliRunner()


def test_history_splice_inserts_correctly(tmp_path: Path) -> None:
    # GIVEN a shared session with 2 pairs
    history: list[ChatMessageHistoryItem] = [
        # Pair 0
        UserChatMessage(content="u0", mode=Mode.CONVERSATION, timestamp="t0"),
        AssistantChatMessage(
            content="a0",
            mode=Mode.CONVERSATION,
            timestamp="t0",
            model="m",
            duration_ms=1,
        ),
        # Pair 1
        UserChatMessage(content="u1", mode=Mode.CONVERSATION, timestamp="t1"),
        AssistantChatMessage(
            content="a1",
            mode=Mode.CONVERSATION,
            timestamp="t1",
            model="m",
            duration_ms=1,
        ),
    ]
    session_data = SessionData(
        model="test",
        chat_history={i: m for i, m in enumerate(history)},
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
    history_list = [
        UserChatMessage(content="u", mode=Mode.CONVERSATION, timestamp="ts"),
        AssistantChatMessage(
            content="a",
            mode=Mode.CONVERSATION,
            timestamp="ts",
            model="m",
            duration_ms=0,
        ),
    ]
    init_shared_session(
        tmp_path,
        SessionData(
            model="m",
            chat_history={i: m for i, m in enumerate(history_list)},
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
    init_shared_session(tmp_path, SessionData(model="m", chat_history={}))

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["history-splice", "999", "888", "--at-index", "0"])

    assert result.exit_code == 1
    assert "Message ID 999 or 888 not found." in result.stderr


def test_history_splice_validates_user_role(tmp_path: Path) -> None:
    # GIVEN a shared session (empty)
    # We create artificial records to test ID validation
    init_shared_session(tmp_path, SessionData(model="m", chat_history={}))

    project_root = tmp_path
    history_root = project_root / ".aico" / "history"
    store = HistoryStore(history_root)

    # Store returns IDs for appended records
    # Create two ASSISTANT records
    rec1 = HistoryRecord(role="assistant", content="A1", mode=Mode.CONVERSATION, timestamp="t1")
    rec2 = HistoryRecord(role="assistant", content="A2", mode=Mode.CONVERSATION, timestamp="t2")

    id1 = store.append(rec1)
    id2 = store.append(rec2)

    # WHEN I try to splice them as if id1 is the User
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["history-splice", str(id1), str(id2), "--at-index", "0"])

    # THEN it should fail with a role error for the first ID (User ID)
    assert result.exit_code != 0
    assert f"Message {id1} is role 'assistant', expected 'user'" in result.stderr


def test_history_splice_validates_assistant_role(tmp_path: Path) -> None:
    # GIVEN a shared session
    init_shared_session(tmp_path, SessionData(model="m", chat_history={}))

    project_root = tmp_path
    history_root = project_root / ".aico" / "history"
    store = HistoryStore(history_root)

    # Create two USER records
    rec1 = HistoryRecord(role="user", content="U1", mode=Mode.CONVERSATION, timestamp="t1")
    rec2 = HistoryRecord(role="user", content="U2", mode=Mode.CONVERSATION, timestamp="t2")

    id1 = store.append(rec1)
    id2 = store.append(rec2)

    # WHEN I try to splice them as if id2 is the Assistant
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["history-splice", str(id1), str(id2), "--at-index", "0"])

    # THEN it should fail with a role error for the second ID (Assistant ID)
    assert result.exit_code != 0
    assert f"Message {id2} is role 'user', expected 'assistant'" in result.stderr


def test_history_splice_shifts_metadata_pointers(tmp_path: Path) -> None:
    # GIVEN a shared session with 3 pairs
    history: list[ChatMessageHistoryItem] = [
        UserChatMessage(content="u0", mode=Mode.CONVERSATION, timestamp="t0"),
        AssistantChatMessage(content="a0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=0),
        UserChatMessage(content="u1", mode=Mode.CONVERSATION, timestamp="t1"),
        AssistantChatMessage(content="a1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=0),
        UserChatMessage(content="u2", mode=Mode.CONVERSATION, timestamp="t2"),
        AssistantChatMessage(content="a2", mode=Mode.CONVERSATION, timestamp="t2", model="m", duration_ms=0),
    ]
    init_shared_session(tmp_path, SessionData(model="test", chat_history={i: m for i, m in enumerate(history)}))

    # Manually configure indices: start at pair 1, exclude pair 2
    view_path = tmp_path / ".aico" / "sessions" / "main.json"
    view = load_view(view_path)
    view.history_start_pair = 1
    view.excluded_pairs = [2]
    save_view(view_path, view)

    # Create dummy records to splice
    store = HistoryStore(tmp_path / ".aico" / "history")
    u_new = store.append(HistoryRecord(role="user", content="u_new", mode=Mode.CONVERSATION))
    a_new = store.append(HistoryRecord(role="assistant", content="a_new", mode=Mode.CONVERSATION))

    # WHEN splicing at index 1 (shifting pairs 1 and 2)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["history-splice", str(u_new), str(a_new), "--at-index", "1"])
    assert result.exit_code == 0

    # THEN metadata pointers should have shifted
    updated_view = load_view(view_path)
    assert updated_view.history_start_pair == 2
    assert updated_view.excluded_pairs == [3]


def test_history_splice_preserves_pointers_before_splice_index(tmp_path: Path) -> None:
    # GIVEN a shared session with 3 pairs
    history: list[ChatMessageHistoryItem] = [
        UserChatMessage(content="u0", mode=Mode.CONVERSATION, timestamp="t0"),
        AssistantChatMessage(content="a0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=0),
        UserChatMessage(content="u1", mode=Mode.CONVERSATION, timestamp="t1"),
        AssistantChatMessage(content="a1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=0),
        UserChatMessage(content="u2", mode=Mode.CONVERSATION, timestamp="t2"),
        AssistantChatMessage(content="a2", mode=Mode.CONVERSATION, timestamp="t2", model="m", duration_ms=0),
    ]
    init_shared_session(tmp_path, SessionData(model="test", chat_history={i: m for i, m in enumerate(history)}))

    view_path = tmp_path / ".aico" / "sessions" / "main.json"
    view = load_view(view_path)
    view.history_start_pair = 0
    view.excluded_pairs = [0]
    save_view(view_path, view)

    # Create dummy records to splice
    store = HistoryStore(tmp_path / ".aico" / "history")
    u_new = store.append(HistoryRecord(role="user", content="u_new", mode=Mode.CONVERSATION))
    a_new = store.append(HistoryRecord(role="assistant", content="a_new", mode=Mode.CONVERSATION))

    # WHEN splicing at index 2 (only shifting pair 2)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["history-splice", str(u_new), str(a_new), "--at-index", "2"])
    assert result.exit_code == 0

    # THEN metadata pointers at index 0 should remain unchanged
    updated_view = load_view(view_path)
    assert updated_view.history_start_pair == 0
    assert updated_view.excluded_pairs == [0]
