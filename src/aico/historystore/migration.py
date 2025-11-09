from __future__ import annotations

from pathlib import Path

from aico.core.session_context import find_message_pairs, map_history_start_index_to_pair
from aico.lib.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    DerivedContent,
    SessionData,
    TokenUsage,
    UserChatMessage,
    UserDerivedMeta,
)

from .history_store import HistoryStore
from .models import HistoryRecord, SessionView, UserMetaEnvelope
from .session_view import find_message_pairs_in_view, save_view


def from_legacy_session(
    session_data: SessionData,
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
        record: HistoryRecord | None = None

        if isinstance(msg, UserChatMessage):
            user_meta = UserDerivedMeta(passthrough=msg.passthrough, piped_content=msg.piped_content)
            has_meta = bool(user_meta.model_dump(exclude_defaults=True))
            record = HistoryRecord(
                role="user",
                content=msg.content,
                mode=msg.mode,
                timestamp=msg.timestamp,
                derived=UserMetaEnvelope(aico_user_meta=user_meta) if has_meta else None,
            )
        else:
            # AssistantChatMessage branch
            record = HistoryRecord(
                role="assistant",
                content=msg.content,
                mode=msg.mode,
                timestamp=msg.timestamp,
                model=msg.model,
                token_usage=msg.token_usage,
                cost=msg.cost,
                duration_ms=msg.duration_ms,
                derived=msg.derived,
            )

        if record:
            idx = store.append(record)
            message_indices.append(idx)

    # Re-calculate history_start_pair from the legacy index, as SessionData defaults it to 0.
    history_start_pair = map_history_start_index_to_pair(session_data.chat_history, session_data.history_start_index)

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
    passthrough: bool = False
    piped_content: str | None = None

    if isinstance(rec.derived, UserMetaEnvelope):
        meta = rec.derived.aico_user_meta
        passthrough = meta.passthrough
        piped_content = meta.piped_content

    return UserChatMessage(
        role="user",
        content=rec.content,
        mode=rec.mode,
        timestamp=rec.timestamp,
        is_excluded=is_excluded,
        passthrough=passthrough,
        piped_content=piped_content,
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
) -> list[ChatMessageHistoryItem]:
    """Reconstructs strongly-typed ChatMessageHistoryItem objects from a view."""
    records = store.read_many(view.message_indices)
    pair_positions = find_message_pairs_in_view(store, view)
    excluded_pair_set = set(view.excluded_pairs)
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


def to_legacy_session(store: HistoryStore, view: SessionView) -> dict[str, object]:
    """
    Reconstructs a legacy-like session dictionary from a SessionView + HistoryStore.
    """
    chat_history = reconstruct_chat_history(store, view)

    # Map history_start_pair back to legacy history_start_index
    pairs = find_message_pairs(chat_history)
    if view.history_start_pair >= len(pairs):
        history_start_index = len(chat_history)
    elif view.history_start_pair <= 0:
        history_start_index = 0
    else:
        history_start_index = pairs[view.history_start_pair].user_index

    session_data = SessionData(
        model=view.model,
        context_files=list(view.context_files),
        chat_history=chat_history,
        history_start_index=history_start_index,
        history_start_pair=view.history_start_pair,
        excluded_pairs=list(view.excluded_pairs),
    )

    # Dump the complete SessionData model to a dictionary that matches the old format.
    # We must manually add back `history_start_index` because it's excluded from serialization by default
    # in the SessionData model for forward compatibility.
    legacy_dict: dict[str, object] = session_data.model_dump(exclude={"history_start_pair", "excluded_pairs"})
    legacy_dict["history_start_index"] = history_start_index
    return legacy_dict
