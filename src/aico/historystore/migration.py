from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from aico.lib.history_utils import (
    find_message_pairs_from_records,
)
from aico.lib.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    DerivedContent,
    Mode,
    TokenUsage,
    UserChatMessage,
)

from .history_store import HistoryStore
from .models import HistoryRecord, SessionView
from .session_view import save_view

# --- Legacy Schemas (Migration Source) ---


class LegacyUserChatMessage(BaseModel):
    role: Literal["user"]
    content: str
    mode: Mode
    timestamp: str
    piped_content: str | None = None
    passthrough: bool = False
    is_excluded: bool = False


class LegacyAssistantChatMessage(BaseModel):
    role: Literal["assistant"]
    content: str
    mode: Mode
    timestamp: str
    model: str
    duration_ms: int
    derived: DerivedContent | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None
    is_excluded: bool = False


type LegacyChatMessage = LegacyUserChatMessage | LegacyAssistantChatMessage


class LegacySessionSnapshot(BaseModel):
    model: str
    context_files: list[str] = Field(default_factory=list)
    chat_history: list[LegacyChatMessage] = Field(default_factory=list)
    # Old Format Fields
    history_start_index: int | None = None
    total_pairs_in_history: int | None = None
    # Intermediate Format Fields (Single file, but new schema)
    history_start_pair: int | None = None
    excluded_pairs: list[int] | None = None


# --- Migration Logic ---


def from_legacy_session(
    session_data: LegacySessionSnapshot,
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

    # Helper because the generic `find_message_pairs` expects objects with `.role`
    # and these Pydantic models have it.
    from aico.lib.history_utils import find_message_pairs

    for msg in session_data.chat_history:
        if isinstance(msg, LegacyUserChatMessage):
            # Convert to runtime model to use existing conversion logic,
            # or create HistoryRecord directly. Creating directly is cleaner here.
            record = HistoryRecord(
                role="user",
                content=msg.content,
                mode=msg.mode,
                timestamp=msg.timestamp,
                passthrough=msg.passthrough,
                piped_content=msg.piped_content,
            )
        else:
            record = HistoryRecord(
                role="assistant",
                content=msg.content,
                mode=msg.mode,
                model=msg.model,
                timestamp=msg.timestamp,
                token_usage=msg.token_usage,
                cost=msg.cost,
                duration_ms=msg.duration_ms,
                derived=msg.derived,
            )

        idx = store.append(record)
        message_indices.append(idx)

    # Inline mapping logic to avoid dependency on runtime util if it changes,
    # though generic functions in history_utils should be stable.
    # Using find_message_pairs to get pairs from legacy messages.
    pairs_idx = find_message_pairs(session_data.chat_history)  # type: ignore

    # 1. Resolve Start Pair (Prefer new format, fallback to old)
    if session_data.history_start_pair is not None:
        history_start_pair = session_data.history_start_pair
    else:
        # Fallback: Calculate from message index
        legacy_history_start_index = session_data.history_start_index or 0
        history_start_pair = len(pairs_idx)
        if legacy_history_start_index < 0:
            history_start_pair = 0
        elif legacy_history_start_index < len(session_data.chat_history):
            found = False
            for i, pair in enumerate(pairs_idx):
                if pair.user_index >= legacy_history_start_index:
                    history_start_pair = i
                    found = True
                    break
            if not found:
                history_start_pair = len(pairs_idx)

    # 2. Resolve Excluded Pairs (Prefer new format, fallback to old flags)
    excluded_pairs: list[int] = []
    if session_data.excluded_pairs is not None:
        excluded_pairs = list(session_data.excluded_pairs)
    else:
        # Fallback: Scan messages for flags
        for i, pair in enumerate(pairs_idx):
            u_msg = session_data.chat_history[pair.user_index]
            a_msg = session_data.chat_history[pair.assistant_index]
            if u_msg.is_excluded and a_msg.is_excluded:
                excluded_pairs.append(i)

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


def deserialize_user_record(rec: HistoryRecord) -> UserChatMessage:
    return UserChatMessage(
        role="user",
        content=rec.content,
        mode=rec.mode,
        timestamp=rec.timestamp,
        passthrough=rec.passthrough,
        piped_content=rec.piped_content,
    )


def deserialize_assistant_record(
    rec: HistoryRecord,
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
    )


def reconstruct_chat_history(
    store: HistoryStore,
    view: SessionView,
    start_pair: int | None = None,
    include_excluded: bool = False,
) -> list[ChatMessageHistoryItem]:
    """
    Reconstructs strongly-typed ChatMessageHistoryItem objects from a view.

    Optimized to only read the active part of the history from disk.

    Args:
        start_pair: The pair index to start from. If None, uses view.history_start_pair (active window).
                    Use 0 for full history.
        include_excluded: If True, excluded messages are included in the returned list.
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

    # Only calculate exclusions if we are NOT including them
    excluded_message_positions: set[int] = set()
    if not include_excluded:
        pair_positions = find_message_pairs_from_records(records)
        excluded_pair_set = {p - effective_start_pair for p in view.excluded_pairs if p >= effective_start_pair}
        excluded_message_positions = {
            pos
            for pair_idx, (u_pos, a_pos) in enumerate(pair_positions)
            if pair_idx in excluded_pair_set
            for pos in (u_pos, a_pos)
        }

    chat_history: list[ChatMessageHistoryItem] = []
    for pos, rec in enumerate(records):
        if pos in excluded_message_positions:
            continue

        if rec.role == "user":
            chat_history.append(deserialize_user_record(rec))
        else:
            chat_history.append(deserialize_assistant_record(rec, view.model))
    return chat_history


def reconstruct_full_chat_history(
    store: HistoryStore,
    view: SessionView,
    include_excluded: bool = True,
) -> list[ChatMessageHistoryItem]:
    """
    Reconstructs strongly-typed ChatMessageHistoryItem objects for the full history of a view.
    """
    return reconstruct_chat_history(store, view, start_pair=0, include_excluded=include_excluded)
