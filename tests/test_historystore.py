# pyright: standard

from pathlib import Path
from typing import Literal

from aico.historystore import (
    SHARD_SIZE,
    HistoryRecord,
    HistoryStore,
    Mode,
    SessionView,
    append_pair_to_view,
    dumps_history_record,
    edit_message,
    find_message_pairs_in_view,
    fork_view,
    load_history_record,
    load_view,
    save_view,
    switch_active_pointer,
)


def _make_record(role: Literal["user", "assistant"], content: str, mode: Mode = Mode.CONVERSATION) -> HistoryRecord:
    return HistoryRecord(role=role, content=content, mode=mode)


def test_history_record_serialization_round_trip_single_line() -> None:
    # GIVEN a history record with simple content
    rec = HistoryRecord(role="user", content="hello world", mode=Mode.CONVERSATION)

    # WHEN it is serialized
    line = dumps_history_record(rec)

    # THEN the JSON is a single line without newline chars
    assert "\n" not in line and "\r" not in line
    # AND the deserialized record matches the original
    rec2 = load_history_record(line)
    assert rec2 == rec


def test_history_record_allows_newlines_and_serializes_single_line() -> None:
    # GIVEN a record with newline content
    rec = HistoryRecord(role="assistant", content="line1\nline2\r\nline3", mode=Mode.DIFF, model="m")

    # WHEN it is serialized
    line = dumps_history_record(rec)

    # THEN serialization stays single-line (newlines are escaped)
    assert "\n" not in line and "\r" not in line
    # AND round-trip preserves the original content with newlines
    parsed = load_history_record(line)
    assert parsed.content == "line1\nline2\r\nline3"
    assert parsed.role == "assistant"
    assert parsed.mode == Mode.DIFF


def test_session_view_validates_indices() -> None:
    # GIVEN that a valid SessionView can be created
    view = SessionView(model="m", message_indices=[0, 1, 2], history_start_pair=0, excluded_pairs=[1])
    assert view.model == "m"

    import pytest

    # WHEN creating SessionViews with various invalid negative indices
    # THEN a ValueError is raised for each case
    with pytest.raises(ValueError):
        _ = SessionView(model="m", message_indices=[-1], history_start_pair=0)
    with pytest.raises(ValueError):
        _ = SessionView(model="m", message_indices=[0], history_start_pair=-5)
    with pytest.raises(ValueError):
        _ = SessionView(model="m", message_indices=[0], excluded_pairs=[-2])


def test_shard_size_constant() -> None:
    assert SHARD_SIZE == 10_000


def test_append_and_next_index_with_shards(tmp_path: Path) -> None:
    # GIVEN a history store with a small shard size for testing
    store = HistoryStore(tmp_path / "history", shard_size=5)

    # WHEN appending 7 records (which should span 2 shards)
    indices: list[int] = []
    for i in range(7):
        idx = store.append(_make_record("user", f"m{i}"))
        indices.append(idx)

    # THEN the indices are sequential and next_index reflects the total
    assert indices == list(range(7))
    assert store.next_index() == 7
    # AND the expected shard files exist
    assert (tmp_path / "history" / "0.jsonl").is_file()
    assert (tmp_path / "history" / "5.jsonl").is_file()
    # AND reading the first and last records returns the correct content
    rec0 = store.read(0)
    rec6 = store.read(6)
    assert rec0.content == "m0" and rec0.role == "user"
    assert rec6.content == "m6" and rec6.role == "user"


def test_read_many_groups_by_shard(tmp_path: Path) -> None:
    # GIVEN a store with several shards
    store = HistoryStore(tmp_path / "history", shard_size=3)
    for i in range(8):
        _ = store.append(_make_record("assistant" if i % 2 else "user", f"idx {i}", mode=Mode.RAW))

    # WHEN reading a mixed set of indices from multiple shards in a specific order
    order = [4, 1, 2, 5, 7]
    records = store.read_many(order)

    # THEN the records are returned in the same order with matching content
    contents = [r.content for r in records]
    assert contents == [f"idx {i}" for i in order]


def test_append_pair_returns_sequential_indices(tmp_path: Path) -> None:
    # GIVEN a fresh store and a user/assistant record pair
    store = HistoryStore(tmp_path / "history")
    u = HistoryRecord(role="user", content="hello\nwith newline", mode=Mode.CONVERSATION)
    a = HistoryRecord(role="assistant", content="world", mode=Mode.CONVERSATION)

    # WHEN appending the pair
    u_idx, a_idx = store.append_pair(u, a)

    # THEN the indices are sequential and readable
    assert a_idx == u_idx + 1
    assert store.read(u_idx).content == "hello\nwith newline"
    assert store.read(a_idx).role == "assistant"


def test_session_view_io_and_reconstruction(tmp_path: Path) -> None:
    # GIVEN a HistoryStore with a conversation history including a dangling message
    store = HistoryStore(tmp_path / "history", shard_size=10_000)
    u0 = store.append(HistoryRecord(role="user", content="p0", mode=Mode.CONVERSATION))
    a0 = store.append(HistoryRecord(role="assistant", content="r0", mode=Mode.CONVERSATION, model="m"))
    d1 = store.append(HistoryRecord(role="user", content="dangling", mode=Mode.RAW))
    u2 = store.append(HistoryRecord(role="user", content="p2", mode=Mode.CONVERSATION))
    a2 = store.append(HistoryRecord(role="assistant", content="r2", mode=Mode.CONVERSATION, model="m"))
    view = SessionView(model="m", message_indices=[u0, a0, d1, u2, a2], history_start_pair=0, excluded_pairs=[])
    view_path = tmp_path / "sessions" / "main.json"

    # WHEN the session view is saved and reloaded
    save_view(view_path, view)
    loaded = load_view(view_path)

    # THEN the saved file is compact (single-line JSON)
    text = view_path.read_text(encoding="utf-8")
    assert "\n" not in text and "\r" not in text
    # AND the loaded view matches the original
    assert loaded == view
    # AND reconstructing messages yields the correct content and order
    records = store.read_many(loaded.message_indices)
    assert [r.role for r in records] == ["user", "assistant", "user", "user", "assistant"]
    assert records[1].model == "m"
    assert records[0].mode == Mode.CONVERSATION


def test_find_message_pairs_in_view_logic(tmp_path: Path) -> None:
    # GIVEN a store with a conversation history including a dangling message
    store = HistoryStore(tmp_path / "history")
    # History: user0, asst0, dangling_user, user1, asst1
    indices = [
        store.append(HistoryRecord(role="user", content="p0", mode=Mode.CONVERSATION)),
        store.append(HistoryRecord(role="assistant", content="r0", mode=Mode.CONVERSATION)),
        store.append(HistoryRecord(role="user", content="d", mode=Mode.RAW)),
        store.append(HistoryRecord(role="user", content="p1", mode=Mode.CONVERSATION)),
        store.append(HistoryRecord(role="assistant", content="r1", mode=Mode.CONVERSATION)),
    ]
    view = SessionView(model="m", message_indices=indices, history_start_pair=0)

    # WHEN finding message pairs
    pairs = find_message_pairs_in_view(store, view)
    # THEN the correct pairs are identified by their positions in the view
    assert pairs == [(0, 1), (3, 4)]


def test_edit_message_appends_and_repoints(tmp_path: Path) -> None:
    # GIVEN a store with a simple user/assistant pair and a view pointing at them
    store = HistoryStore(tmp_path / "history")
    u_idx = store.append(HistoryRecord(role="user", content="prompt 0", mode=Mode.CONVERSATION))
    a_idx = store.append(HistoryRecord(role="assistant", content="resp 0", mode=Mode.CONVERSATION))
    view = SessionView(model="m", message_indices=[u_idx, a_idx])

    # WHEN editing the assistant message content
    new_idx = edit_message(store, view, view_msg_position=1, new_content="resp 0 - edited")

    # THEN the store contains a new record with edit_of pointing to the original
    original = store.read(a_idx)
    edited = store.read(new_idx)
    assert edited.content == "resp 0 - edited"
    assert edited.edit_of == a_idx
    assert original.content == "resp 0"  # original is untouched

    # AND the view now points to the new record
    assert view.message_indices[1] == new_idx

    # AND reconstruction yields the updated assistant content
    records = store.read_many(view.message_indices)
    assert records[0].content == "prompt 0"
    assert records[1].content == "resp 0 - edited"


def test_edit_message_chain_and_manual_revert(tmp_path: Path) -> None:
    # GIVEN a store and view with a single user/assistant pair
    store = HistoryStore(tmp_path / "history")
    u = store.append(HistoryRecord(role="user", content="p", mode=Mode.CONVERSATION))
    a = store.append(HistoryRecord(role="assistant", content="r1", mode=Mode.CONVERSATION))
    view = SessionView(model="m", message_indices=[u, a])

    # WHEN applying two edits in sequence to the assistant's response
    idx2 = edit_message(store, view, 1, "r2")
    idx3 = edit_message(store, view, 1, "r3")

    # THEN each new record points to its immediate predecessor
    r2 = store.read(idx2)
    r3 = store.read(idx3)
    assert r2.edit_of == a
    assert r3.edit_of == idx2

    # WHEN reverting manually by repointing the view to the predecessor
    assert r3.edit_of is not None
    view.message_indices[1] = r3.edit_of  # revert to r2
    # THEN reconstruction shows the reverted content
    records = store.read_many(view.message_indices)
    assert records[1].content == "r2"

    # WHEN reverting again to the original
    prev = store.read(view.message_indices[1]).edit_of
    assert prev is not None
    view.message_indices[1] = prev  # revert to original 'a'
    # THEN reconstruction shows the original content
    records2 = store.read_many(view.message_indices)
    assert records2[1].content == "r1"


def test_append_pair_to_view_helper(tmp_path: Path) -> None:
    # GIVEN an empty store and view
    store = HistoryStore(tmp_path / "history")
    view = SessionView(model="m")

    # WHEN appending a pair via helper
    u_rec = HistoryRecord(role="user", content="u", mode=Mode.CONVERSATION)
    a_rec = HistoryRecord(role="assistant", content="a", mode=Mode.CONVERSATION)
    u_idx, a_idx = append_pair_to_view(store, view, u_rec, a_rec)

    # THEN indices are sequential and stored, and view updated
    assert a_idx == u_idx + 1
    assert view.message_indices == [u_idx, a_idx]
    assert store.read(u_idx).content == "u"
    assert store.read(a_idx).content == "a"


def test_fork_view_truncates_at_pair(tmp_path: Path) -> None:
    # GIVEN a store and view with two pairs and a dangling message
    store = HistoryStore(tmp_path / "history")
    u0 = store.append(HistoryRecord(role="user", content="p0", mode=Mode.CONVERSATION))
    a0 = store.append(HistoryRecord(role="assistant", content="r0", mode=Mode.CONVERSATION))
    d = store.append(HistoryRecord(role="user", content="dangling", mode=Mode.RAW))
    u1 = store.append(HistoryRecord(role="user", content="p1", mode=Mode.CONVERSATION))
    a1 = store.append(HistoryRecord(role="assistant", content="r1", mode=Mode.CONVERSATION))
    view = SessionView(model="m", message_indices=[u0, a0, d, u1, a1])

    # WHEN forking until the first pair (index 0)
    new_view_path = fork_view(store, view, until_pair=0, new_name="fork0", sessions_dir=tmp_path / "sessions")

    # THEN new view file exists and only contains first pair's messages
    forked = load_view(new_view_path)
    assert forked.message_indices == [u0, a0]
    assert forked.model == view.model
    assert forked.excluded_pairs == []


def test_switch_active_pointer_writes_pointer_file(tmp_path: Path) -> None:
    # GIVEN a sessions directory with a view
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    view_path = sessions_dir / "main.json"
    save_view(view_path, SessionView(model="m"))

    # WHEN switching active pointer
    pointer_file = tmp_path / ".ai_session.json"
    switch_active_pointer(pointer_file, view_path)

    # THEN pointer file exists with correct JSON content
    content = pointer_file.read_text(encoding="utf-8")
    import json

    data: dict[str, object] = json.loads(content)
    assert data["type"] == "aico_session_pointer_v1"
    assert data["path"] == "sessions/main.json"


def test_history_shard_created_with_secure_permissions(tmp_path: Path) -> None:
    store_path = tmp_path / "history"
    store = HistoryStore(store_path)

    # Append a line to create a new shard file
    line = '{"role": "user", "content": "test"}'
    store._append_line(store_path / "0.jsonl", line)

    shard_file = next(store_path.glob("*.jsonl"))
    assert shard_file.is_file()
    mode = shard_file.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0600 for shard {shard_file}, got {oct(mode)}"

    # Parent dir should be 0700 if newly created
    if not store_path.exists():
        parent_mode = store_path.stat().st_mode & 0o777
        assert parent_mode == 0o700
