# pyright: standard

from pathlib import Path
from typing import Any, Literal

from aico.historystore import (
    HistoryStore,
    find_message_pairs_in_view,
)
from aico.historystore.migration import LegacySessionSnapshot, from_legacy_session
from aico.historystore.models import SessionView as SessionViewModel
from aico.serialization import convert


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
            # Pair 1 (excluded)
            _make_legacy_chat_item("user", "u1", is_excluded=True),
            _make_legacy_chat_item("assistant", "a1", is_excluded=True),
            # Pair 2
            _make_legacy_chat_item("user", "u2"),
            _make_legacy_chat_item("assistant", "a2"),
            # Dangling user message
            _make_legacy_chat_item("user", "dangling-at-end"),
        ],
        "history_start_index": 2,  # Start at pair 1 (u1/a1)
    }

    history_root = tmp_path / "history"
    sessions_dir = tmp_path / "sessions"

    # WHEN migrating forward to sharded store + view
    session_data = convert(legacy, LegacySessionSnapshot)
    view = from_legacy_session(
        session_data=session_data,
        history_root=history_root,
        sessions_dir=sessions_dir,
        name="main",
        shard_size=5,
    )

    # THEN the SessionView is created with correct indices and metadata
    assert isinstance(view, SessionViewModel)
    assert view.model == legacy["model"]
    assert view.context_files == legacy["context_files"]
    assert len(view.message_indices) == len(legacy["chat_history"])
    assert view.history_start_pair == 1  # Corresponds to legacy history_start_index: 2
    assert view.excluded_pairs == [1]


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
    session_data = convert(legacy, LegacySessionSnapshot)
    view = from_legacy_session(
        session_data=session_data,
        history_root=history_root,
        sessions_dir=sessions_dir,
        name="empty",
    )

    # THEN view has no messages and start pair = 0
    assert view.message_indices == []
    assert view.history_start_pair == 0
    assert view.excluded_pairs == []


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
    session_data = convert(legacy, LegacySessionSnapshot)
    view = from_legacy_session(
        session_data=session_data,
        history_root=history_root,
        sessions_dir=sessions_dir,
        name="after",
    )

    # THEN start pair is len(pairs) (cleared context)
    assert view.history_start_pair == 2


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
    session_data = convert(legacy, LegacySessionSnapshot)
    view = from_legacy_session(
        session_data=session_data,
        history_root=history_root,
        sessions_dir=sessions_dir,
        name="partial",
    )

    # THEN excluded_pairs is empty because pair exclusion requires both messages excluded
    assert view.excluded_pairs == []

    # AND pairs detected match expectation
    store = HistoryStore(history_root)
    pairs = find_message_pairs_in_view(store, view)
    assert pairs == [(0, 1), (2, 3)]


def test_migration_intermediate_format(tmp_path: Path) -> None:
    """
    Tests migration of the 'intermediate' single-file format which used
    history_start_pair and excluded_pairs directly, instead of the ancient flags.
    """
    # GIVEN an intermediate legacy session (single file, but new schema fields)
    # Note: 'history_start_index' is missing, relying on 'history_start_pair'
    legacy: dict[str, Any] = {
        "model": "m",
        "context_files": [],
        "chat_history": [
            _make_legacy_chat_item("user", "u0"),
            _make_legacy_chat_item("assistant", "a0"),
            _make_legacy_chat_item("user", "u1"),
            _make_legacy_chat_item("assistant", "a1"),
        ],
        # These keys should take precedence over missing or default ancient keys
        "history_start_pair": 1,
        "excluded_pairs": [0],
    }
    history_root = tmp_path / "history"
    sessions_dir = tmp_path / "sessions"

    # WHEN migrating forward
    session_data = convert(legacy, LegacySessionSnapshot)
    view = from_legacy_session(
        session_data=session_data,
        history_root=history_root,
        sessions_dir=sessions_dir,
        name="intermediate",
    )

    # THEN the view adopts the explicit fields
    assert view.history_start_pair == 1
    assert view.excluded_pairs == [0]

    # AND indices are valid
    assert len(view.message_indices) == 4


def test_migration_sanitizes_legacy_string_display_content(tmp_path: Path) -> None:
    # GIVEN a legacy session where an assistant message has a string in display_content
    legacy: dict[str, object] = {
        "model": "m",
        "context_files": [],
        "chat_history": [
            _make_legacy_chat_item("user", "u0"),
            {
                "role": "assistant",
                "content": "a0",
                "mode": "diff",
                "timestamp": "ts1",
                "model": "m",
                "duration_ms": 100,
                "derived": {
                    "unified_diff": "some-diff",
                    "display_content": "Legacy string content that should be sanitized",
                },
                "is_excluded": False,
            },
        ],
        "history_start_index": 0,
    }
    history_root = tmp_path / "history"
    sessions_dir = tmp_path / "sessions"

    # WHEN migrating forward
    from aico.serialization import convert

    session_data = convert(legacy, LegacySessionSnapshot)
    view = from_legacy_session(
        session_data=session_data,
        history_root=history_root,
        sessions_dir=sessions_dir,
        name="sanitized",
    )

    # THEN the record in the store has display_content set to None
    store = HistoryStore(history_root)
    assistant_record = store.read_many([view.message_indices[1]])[0]

    assert assistant_record.derived is not None

    # Fix linting by narrowing the type of derived
    from aico.models import DerivedContent
    from aico.serialization import convert

    match assistant_record.derived:
        case dict() as d:
            assert d.get("display_content") is None
            assert d.get("unified_diff") == "some-diff"
        case DerivedContent() as dc:
            assert dc.display_content is None
            assert dc.unified_diff == "some-diff"
        case _:
            # Fallback for msgspec.Struct that isn't DerivedContent yet
            dc = convert(assistant_record.derived, DerivedContent)
            assert dc.display_content is None
            assert dc.unified_diff == "some-diff"
