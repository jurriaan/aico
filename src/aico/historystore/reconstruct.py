"""
Fast reconstruction logic for converting HistoryStore records to ChatMessageHistoryItem objects.
This module contains the frequently-used reconstruction functions that are needed on every aico startup.
"""

from aico.history_utils import find_message_pairs_from_records
from aico.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    DerivedContent,
    TokenUsage,
    UserChatMessage,
)
from aico.serialization import convert

from .history_store import HistoryStore
from .models import HistoryRecord, SessionView


def deserialize_user_record(rec: HistoryRecord) -> UserChatMessage:
    return UserChatMessage(
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

    derived_obj: DerivedContent | None = None
    if rec.derived is not None:
        raw_derived = rec.derived
        # Handle sanitization of legacy string display_content
        match raw_derived:
            case {"display_content": str()} as d if isinstance(d, dict):
                cleaned: dict[str, object] = dict(d)  # pyright: ignore[reportUnknownArgumentType]
                cleaned["display_content"] = None
                raw_derived = cleaned
            case _:
                pass

        # When loaded from JSON by msgspec, derived might be a dict.
        # Convert it to the Typed/frozen dataclass.
        derived_obj = raw_derived if isinstance(raw_derived, DerivedContent) else convert(raw_derived, DerivedContent)

    return AssistantChatMessage(
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
) -> dict[int, ChatMessageHistoryItem]:
    """
    Reconstructs strongly-typed ChatMessageHistoryItem objects from a view.
    Returns a dictionary mapping absolute message indices to records.

    Optimized to only read the active part of the history from disk.

    Args:
        start_pair: The pair index to start from. If None, uses view.history_start_pair (active window).
                    Use 0 for full history.
        include_excluded: If True, excluded messages are included in the returned map.
    """
    if not view.message_indices:
        return {}

    effective_start_pair = view.history_start_pair if start_pair is None else start_pair
    start_message_pos = effective_start_pair * 2
    if start_message_pos >= len(view.message_indices):
        return {}

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

    chat_history: dict[int, ChatMessageHistoryItem] = {}
    for pos, rec in enumerate(records):
        if pos in excluded_message_positions:
            continue

        abs_idx = start_message_pos + pos
        if rec.role == "user":
            chat_history[abs_idx] = deserialize_user_record(rec)
        else:
            chat_history[abs_idx] = deserialize_assistant_record(rec, view.model)
    return chat_history


def reconstruct_full_chat_history(
    store: HistoryStore,
    view: SessionView,
    include_excluded: bool = True,
) -> dict[int, ChatMessageHistoryItem]:
    """
    Reconstructs strongly-typed ChatMessageHistoryItem objects for the full history of a view.
    """
    return reconstruct_chat_history(store, view, start_pair=0, include_excluded=include_excluded)
