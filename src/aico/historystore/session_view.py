from __future__ import annotations

import json
from pathlib import Path

from aico.lib.history_utils import find_message_pairs_from_records
from aico.lib.models import TokenUsage
from aico.utils import atomic_write_text

from .history_store import HistoryStore
from .models import HistoryDerived, HistoryRecord, SessionView


def load_view(path: Path) -> SessionView:
    """
    Load a SessionView from disk.
    """
    data = path.read_text(encoding="utf-8")
    return SessionView.model_validate_json(data)


def save_view(path: Path, view: SessionView) -> None:
    """
    Atomically save a SessionView to disk using a compact single-line JSON format.
    """
    json_text = view.model_dump_json(indent=None)
    atomic_write_text(path, json_text)


def find_message_pairs_in_view(store: HistoryStore, view: SessionView) -> list[tuple[int, int]]:
    """
    Returns a list of (user_pos, assistant_pos) tuples where positions are indices into view.message_indices.
    Delegates to the internal records-based helper after a single read.
    """
    if not view.message_indices:
        return []
    records = store.read_many(view.message_indices)
    return find_message_pairs_from_records(records)


def edit_message(
    store: HistoryStore,
    view: SessionView,
    view_msg_position: int,
    new_content: str,
    *,
    model: str | None = None,
    derived: HistoryDerived | None = None,
    token_usage: TokenUsage | None = None,
    cost: float | None = None,
    duration_ms: int | None = None,
) -> int:
    """
    Append-and-repoint edit: creates a new record with updated content and edit_of pointing
    to the original global index, then updates the view's pointer at view_msg_position.
    Returns the new global index.

    Optional metadata may be provided to preserve or override fields such as model, derived,
    token usage, cost, and duration for assistant edits. When not provided, original values are kept.
    """
    if not (0 <= view_msg_position < len(view.message_indices)):
        raise IndexError("view_msg_position out of range")

    original_index = view.message_indices[view_msg_position]
    original = store.read(original_index)

    new_record = HistoryRecord(
        role=original.role,
        content=new_content,
        mode=original.mode,
        model=model if model is not None else original.model,
        derived=derived if derived is not None else original.derived,
        token_usage=token_usage if token_usage is not None else original.token_usage,
        cost=cost if cost is not None else original.cost,
        duration_ms=duration_ms if duration_ms is not None else original.duration_ms,
        edit_of=original_index,
    )
    new_index = store.append(new_record)
    view.message_indices[view_msg_position] = new_index
    return new_index


def append_pair_to_view(
    store: HistoryStore,
    view: SessionView,
    user: HistoryRecord,
    assistant: HistoryRecord,
) -> tuple[int, int]:
    """
    Appends a user/assistant pair to the store and extends the view.
    Returns the (user_index, assistant_index).
    """
    u_idx = store.append(user)
    a_idx = store.append(assistant)
    view.message_indices.extend([u_idx, a_idx])
    return u_idx, a_idx


def fork_view(
    store: HistoryStore,
    view: SessionView,
    until_pair: int | None,
    new_name: str,
    sessions_dir: Path,
) -> Path:
    """
    Create a new SessionView file truncated to the end of the specified pair.
    If until_pair is None, a full copy is created.
    Returns path to the new view file.
    """
    pairs = find_message_pairs_in_view(store, view)
    if until_pair is not None:
        if not (0 <= until_pair < len(pairs)):
            raise IndexError("until_pair out of range")
        # End position is assistant message position of that pair + 1 for slicing
        end_pos = pairs[until_pair][1] + 1
        truncated_indices = view.message_indices[:end_pos]
        # Filter excluded_pairs to those still valid
        new_excluded = [p for p in view.excluded_pairs if p <= until_pair]
    else:
        truncated_indices = list(view.message_indices)
        new_excluded = list(view.excluded_pairs)

    new_view = SessionView(
        model=view.model,
        context_files=list(view.context_files),
        message_indices=truncated_indices,
        history_start_pair=view.history_start_pair if view.history_start_pair <= (until_pair or len(pairs)) else 0,
        excluded_pairs=new_excluded,
    )
    sessions_dir.mkdir(parents=True, exist_ok=True)
    new_path = sessions_dir / f"{new_name}.json"
    save_view(new_path, new_view)
    return new_path


def switch_active_pointer(pointer_file: Path, new_view_path: Path) -> None:
    """
    Atomically write a pointer file referencing the given view path.
    Stores a relative path when possible.
    """
    rel_path: str
    try:
        rel_path = new_view_path.resolve().relative_to(pointer_file.parent.resolve()).as_posix()
    except ValueError:
        rel_path = str(new_view_path.resolve())

    data = {"type": "aico_session_pointer_v1", "path": rel_path}
    json_text = json.dumps(data, separators=(",", ":"))
    atomic_write_text(pointer_file, json_text)
