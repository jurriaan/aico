from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

from aico.lib.models import MessagePairIndices


@runtime_checkable
class HasRole(Protocol):
    @property
    def role(self) -> Literal["user", "assistant"]: ...


def _generic_find_message_pairs(history: Sequence[HasRole]) -> list[tuple[int, int]]:
    """
    Scans a list of objects with a 'role' attribute and identifies user/assistant message pairs.
    A pair is defined as a user message followed immediately by an assistant message.
    Returns a list of (user_index, assistant_index) tuples.
    """
    pairs: list[tuple[int, int]] = []
    i = 0
    while i < len(history) - 1:
        current_msg = history[i]
        next_msg = history[i + 1]
        if current_msg.role == "user" and next_msg.role == "assistant":
            pairs.append((i, i + 1))
            i += 2  # Move to the next potential pair
        else:
            i += 1
    return pairs


def find_message_pairs(chat_history: Sequence[HasRole]) -> list[MessagePairIndices]:
    """
    Wrapper around the generic pair finder for ChatMessageHistoryItem lists.
    """
    positions = _generic_find_message_pairs(chat_history)
    return [MessagePairIndices(user_index=u, assistant_index=a) for u, a in positions]


def find_message_pairs_from_records(records: Sequence[HasRole]) -> list[tuple[int, int]]:
    """
    Wrapper around the generic pair finder for HistoryRecord-like lists.
    """
    return _generic_find_message_pairs(records)


def map_history_start_index_to_pair(chat_history: Sequence[HasRole], history_start_index: int) -> int:
    """
    Map a legacy message-centric history_start_index to a pair index.

    Returns the index of the first pair whose user message index is >= history_start_index.
    If history_start_index is beyond the end of the history, returns len(pairs).
    """
    pairs = find_message_pairs(chat_history)
    if not pairs:
        return 0
    if history_start_index >= len(chat_history):
        return len(pairs)
    for pair_idx, p in enumerate(pairs):
        if p.user_index >= history_start_index:
            return pair_idx
    return len(pairs)
