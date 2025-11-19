from __future__ import annotations

from pathlib import Path

from aico.lib.history_utils import (
    find_message_pairs,
    find_message_pairs_from_records,
    map_history_start_index_to_pair,
)
from aico.lib.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    DerivedContent,
    SessionData,
    TokenUsage,
    UserChatMessage,
)

from .history_store import HistoryStore
from .models import HistoryRecord, SessionView
from .session_view import save_view


def from_legacy_session(
    session_data: SessionData,
    *,
    history_root: Path,
    sessions_dir: Path,
    name: str,
    shard_size: int = 10_000,
) -> SessionView:
    """
    Migrates a legacy session Pydantic Model into sharded history + SessionView.
    Returns the created SessionView (already saved to disk).
    """
    store = HistoryStore(history_root, shard_size=shard_size)
    message_indices: list[int] = []

    for msg in session_data.chat_history:
        if isinstance(msg, UserChatMessage):
            record = HistoryRecord.from_user_message(msg)
        else:
            # AssistantChatMessage branch
            record = HistoryRecord.from_assistant_message(msg)

        idx = store.append(record)
        message_indices.append(idx)

    # Calculate history_start_pair from the legacy index if available on the SessionData object
    legacy_history_start_index = session_data.history_start_index or 0
    history_start_pair = map_history_start_index_to_pair(session_data.chat_history, legacy_history_start_index)

    # Re-calculate excluded_pairs from legacy per-message flags
    pairs = find_message_pairs(session_data.chat_history)
    excluded_pairs = [
        idx
        for idx, p in enumerate(pairs)
        if session_data.chat_history[p.user_index].is_excluded
        and session_data.chat_history[p.assistant_index].is_excluded
    ]

    view = SessionView(
        model=session_data.model,
        context_files=list(session_data.context_files),
        message_indices=message_indices,
        history_start_pair=history_start_pair,
        excluded_pairs=excluded_pairs,
    )

    sessions_dir.mkdir(parents=True, exist_ok=True)
    view_path = sessions_dir / f"{name}.json"
    save_view(view_path, view)
    return view


def deserialize_user_record(rec: HistoryRecord, is_excluded: bool) -> UserChatMessage:
    return UserChatMessage(
        role="user",
        content=rec.content,
        mode=rec.mode,
        timestamp=rec.timestamp,
        is_excluded=is_excluded,
        passthrough=rec.passthrough,
        piped_content=rec.piped_content,
    )


def deserialize_assistant_record(
    rec: HistoryRecord,
    is_excluded: bool,
    view_model: str,
) -> AssistantChatMessage:
    token_usage_obj: TokenUsage | None = rec.token_usage

    derived_obj: DerivedContent | None = rec.derived if isinstance(rec.derived, DerivedContent) else None

    return AssistantChatMessage(
        role="assistant",
        content=rec.content,
        mode=rec.mode,
        timestamp=rec.timestamp,
        model=rec.model or view_model,
        duration_ms=rec.duration_ms or 0,
        derived=derived_obj,
        token_usage=token_usage_obj,
        cost=rec.cost,
        is_excluded=is_excluded,
    )


def reconstruct_chat_history(
    store: HistoryStore,
    view: SessionView,
    start_pair: int | None = None,
) -> list[ChatMessageHistoryItem]:
    """
    Reconstructs strongly-typed ChatMessageHistoryItem objects from a view.

    Optimized to only read the active part of the history from disk.

    Args:
        start_pair: The pair index to start from. If None, uses view.history_start_pair (active window).
                    Use 0 for full history.
    """
    if not view.message_indices:
        return []

    effective_start_pair = view.history_start_pair if start_pair is None else start_pair
    start_message_pos = effective_start_pair * 2
    if start_message_pos >= len(view.message_indices):
        return []

    indices_to_read = view.message_indices[start_message_pos:]
    records = store.read_many(indices_to_read)

    if records:
        if records[0].role != "user":
            raise ValueError(
                f"History data integrity error: Expected first message at index {start_message_pos} "
                + f"(from start pair {effective_start_pair}) to be 'user', but found '{records[0].role}'."
            )
        for i in range(0, len(records) - 1, 2):
            if not (records[i].role == "user" and records[i + 1].role == "assistant"):
                raise ValueError(
                    f"History data integrity error: Mismatched roles at positions {i}, {i + 1}. "
                    + "Expected user/assistant, "
                    + f"found {records[i].role}/{records[i + 1].role}."
                )

    pair_positions = find_message_pairs_from_records(records)

    excluded_pair_set = {p - effective_start_pair for p in view.excluded_pairs if p >= effective_start_pair}
    excluded_message_positions: set[int] = {
        pos
        for pair_idx, (u_pos, a_pos) in enumerate(pair_positions)
        if pair_idx in excluded_pair_set
        for pos in (u_pos, a_pos)
    }

    chat_history: list[ChatMessageHistoryItem] = []
    for pos, rec in enumerate(records):
        is_excluded = pos in excluded_message_positions
        if rec.role == "user":
            chat_history.append(deserialize_user_record(rec, is_excluded))
        else:
            chat_history.append(deserialize_assistant_record(rec, is_excluded, view.model))
    return chat_history


def reconstruct_full_chat_history(
    store: HistoryStore,
    view: SessionView,
) -> list[ChatMessageHistoryItem]:
    """
    Reconstructs strongly-typed ChatMessageHistoryItem objects for the full history of a view.
    """
    return reconstruct_chat_history(store, view, start_pair=0)


def to_legacy_session(store: HistoryStore, view: SessionView) -> dict[str, object]:
    """
    Reconstructs a legacy-like session dictionary from a SessionView + HistoryStore.
    The resulting legacy session will only contain the active window of the view.
    """
    chat_history = reconstruct_chat_history(store, view)

    # Because reconstruct_chat_history now returns only the active window,
    # the start pair for this history is 0. Exclusions are represented by
    # `is_excluded` flags on messages, so `excluded_pairs` list is empty.
    session_data = SessionData(
        model=view.model,
        context_files=list(view.context_files),
        chat_history=chat_history,
        history_start_pair=0,
        excluded_pairs=[],
    )

    # Dump to a dictionary that matches the old format.
    legacy_dict = session_data.model_dump(
        exclude_defaults=True,
        exclude={"history_start_pair", "excluded_pairs", "total_pairs_in_history"},
    )

    # `history_start_index = 0` corresponds to the start of the sliced history.
    legacy_dict["history_start_index"] = 0
    return legacy_dict
