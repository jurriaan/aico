from pathlib import Path

from pydantic import TypeAdapter

from aico.atomic_io import atomic_write_text
from aico.history_utils import find_message_pairs_from_records
from aico.models import SessionPointer

from .history_store import HistoryStore
from .models import HistoryRecord, SessionView


def load_view(path: Path) -> SessionView:
    """
    Load a SessionView from disk.
    """
    data = path.read_text(encoding="utf-8")
    return TypeAdapter(SessionView).validate_json(data)


def save_view(path: Path, view: SessionView) -> None:
    """
    Atomically save a SessionView to disk using a compact single-line JSON format.
    """
    json_text = TypeAdapter(SessionView).dump_json(view, indent=None)
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
    message_index: int,
    new_record: HistoryRecord,
) -> int:
    """
    Replaces the message at message_index with the provided new_record.
    (Actually appends new_record to store and updates the view pointer).
    Returns the new global index.
    """
    if not (0 <= message_index < len(view.message_indices)):
        raise IndexError(f"Message index {message_index} out of range for view.")

    new_idx = store.append(new_record)
    view.message_indices[message_index] = new_idx
    return new_idx


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

    data = SessionPointer(type="aico_session_pointer_v1", path=rel_path)
    json_text = TypeAdapter(SessionPointer).dump_json(data, indent=None)
    atomic_write_text(pointer_file, json_text)
