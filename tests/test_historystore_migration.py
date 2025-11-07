# pyright: standard

from pathlib import Path
from typing import Any, Literal

from aico.historystore import (
    HistoryStore,
    find_message_pairs_in_view,
    from_legacy_session,
    to_legacy_session,
)
from aico.historystore.models import SessionView as SessionViewModel
from aico.lib.models import AssistantChatMessage, UserChatMessage
from aico.lib.session import SessionDataAdapter


def _make_legacy_chat_item(
    role: Literal["user", "assistant"],
    content: str,
    mode: str = "conversation",
    is_excluded: bool = False,
    timestamp: str = "ts",
    model: str = "m",
    duration_ms: int = 0,
) -> dict[str, object]:
    """Creates a legacy message dictionary that satisfies SessionData validation."""
    item: dict[str, object] = {
        "role": role,
        "content": content,
        "mode": mode,
        "timestamp": timestamp,
        "is_excluded": is_excluded,
    }
    if role == "assistant":
        item["model"] = model
        item["duration_ms"] = duration_ms
    return item


def test_migration_forward_and_round_trip(tmp_path: Path) -> None:
    # GIVEN a synthetic legacy session with full metadata on some messages
    legacy_user_with_pipe: dict[str, object] = {
        "role": "user",
        "content": "u0",
        "mode": "conversation",
        "timestamp": "ts0",
        "piped_content": "piped stuff",
        "passthrough": True,
        "is_excluded": False,
    }
    legacy_assistant_with_all: dict[str, object] = {
        "role": "assistant",
        "content": "a0",
        "mode": "diff",
        "timestamp": "ts1",
        "model": "model-for-a0",
        "token_usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "cost": 0.1,
        "duration_ms": 100,
        "derived": {"unified_diff": "diff", "display_content": "display"},
        "is_excluded": False,
    }
    legacy: dict[str, Any] = {
        "model": "test-model",
        "context_files": ["a.py", "b.py"],
        "chat_history": [
            legacy_user_with_pipe,
            legacy_assistant_with_all,
            _make_legacy_chat_item("user", "dangling-before-start"),
            _make_legacy_chat_item("user", "u1", is_excluded=True),
            _make_legacy_chat_item("assistant", "a1", is_excluded=True),
            _make_legacy_chat_item("user", "u2"),
            _make_legacy_chat_item("assistant", "a2"),
        ],
        "history_start_index": 3,
    }

    history_root = tmp_path / "history"
    sessions_dir = tmp_path / "sessions"

    # WHEN migrating forward to sharded store + view
    session_data = SessionDataAdapter.validate_python(legacy)
    view = from_legacy_session(
        session_data, history_root=history_root, sessions_dir=sessions_dir, name="main", shard_size=5
    )

    # THEN the SessionView is created with correct indices and metadata
    assert isinstance(view, SessionViewModel)
    assert view.model == legacy["model"]
    assert view.context_files == legacy["context_files"]
    assert len(view.message_indices) == len(legacy["chat_history"])
    assert view.history_start_pair == 1
    assert view.excluded_pairs == [1]

    # WHEN reconstructing a legacy session from the view
    store = HistoryStore(history_root, shard_size=5)
    legacy_round_trip: dict[str, object] = to_legacy_session(store, view)

    # THEN round-trip preserves basic metadata (validate back into SessionData)
    session_rt = SessionDataAdapter.validate_python(legacy_round_trip)
    assert session_rt.model == legacy["model"]
    assert len(session_rt.chat_history) == len(legacy["chat_history"])

    # THEN round-trip preserves detailed fields for the user message
    user0 = session_rt.chat_history[0]
    assert isinstance(user0, UserChatMessage)
    assert user0.passthrough is True
    assert user0.piped_content == "piped stuff"
    assert user0.timestamp == "ts0"

    # THEN round-trip preserves detailed fields for the assistant message
    asst0 = session_rt.chat_history[1]
    assert isinstance(asst0, AssistantChatMessage)
    assert asst0.timestamp == "ts1"
    assert asst0.token_usage is not None
    assert asst0.token_usage.prompt_tokens == 1
    assert asst0.token_usage.completion_tokens == 2
    assert asst0.token_usage.total_tokens == 3
    assert asst0.cost == 0.1
    assert asst0.duration_ms == 100
    assert asst0.derived is not None
    assert asst0.derived.unified_diff == "diff"
    assert asst0.derived.display_content == "display"

    # AND history_start_index maps back correctly
    assert session_rt.history_start_index == 3


def test_migration_empty_session(tmp_path: Path) -> None:
    # GIVEN an empty legacy session
    legacy: dict[str, object] = {
        "model": "m",
        "context_files": [],
        "chat_history": [],
        "history_start_index": 0,
    }
    history_root = tmp_path / "history"
    sessions_dir = tmp_path / "sessions"

    # WHEN migrating forward
    session_data = SessionDataAdapter.validate_python(legacy)
    view = from_legacy_session(session_data, history_root, sessions_dir, "empty")

    # THEN view has no messages and start pair = 0
    assert view.message_indices == []
    assert view.history_start_pair == 0
    assert view.excluded_pairs == []

    # WHEN migrating back
    store = HistoryStore(history_root)
    legacy_rt: dict[str, object] = to_legacy_session(store, view)

    # THEN round-trip matches original
    session_rt = SessionDataAdapter.validate_python(legacy_rt)
    assert session_rt.chat_history == []
    assert session_rt.history_start_index == 0


def test_migration_history_start_after_last_pair(tmp_path: Path) -> None:
    # GIVEN a legacy session whose history_start_index points after all messages
    legacy: dict[str, object] = {
        "model": "m",
        "context_files": [],
        "chat_history": [
            _make_legacy_chat_item("user", "u0"),
            _make_legacy_chat_item("assistant", "a0"),
            _make_legacy_chat_item("user", "u1"),
            _make_legacy_chat_item("assistant", "a1"),
        ],
        "history_start_index": 10,  # beyond end
    }
    history_root = tmp_path / "history"
    sessions_dir = tmp_path / "sessions"

    # WHEN migrating forward
    session_data = SessionDataAdapter.validate_python(legacy)
    view = from_legacy_session(session_data, history_root, sessions_dir, "after")

    # THEN start pair is len(pairs) (cleared context)
    assert view.history_start_pair == 2

    # WHEN migrating back
    store = HistoryStore(history_root)
    legacy_rt: dict[str, object] = to_legacy_session(store, view)

    # THEN history_start_index points to end
    session_rt = SessionDataAdapter.validate_python(legacy_rt)
    assert session_rt.history_start_index == 4


def test_migration_excludes_only_full_excluded_pairs(tmp_path: Path) -> None:
    # GIVEN a legacy session where only assistant messages are excluded
    legacy: dict[str, object] = {
        "model": "m",
        "context_files": [],
        "chat_history": [
            _make_legacy_chat_item("user", "u0"),
            _make_legacy_chat_item("assistant", "a0", is_excluded=True),
            _make_legacy_chat_item("user", "u1"),
            _make_legacy_chat_item("assistant", "a1"),
        ],
        "history_start_index": 0,
    }
    history_root = tmp_path / "history"
    sessions_dir = tmp_path / "sessions"

    # WHEN migrating forward
    session_data = SessionDataAdapter.validate_python(legacy)
    view = from_legacy_session(session_data, history_root, sessions_dir, "partial")

    # THEN excluded_pairs is empty because pair exclusion requires both messages excluded
    assert view.excluded_pairs == []

    # AND pairs detected match expectation
    store = HistoryStore(history_root)
    pairs = find_message_pairs_in_view(store, view)
    assert pairs == [(0, 1), (2, 3)]
