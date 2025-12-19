from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, runtime_checkable

from aico.models import MessagePairIndices


@runtime_checkable
class HasRole(Protocol):
    @property
    def role(self) -> Literal["user", "assistant"]: ...


def _generic_find_message_pairs(history: Sequence[HasRole] | Mapping[int, HasRole]) -> list[tuple[int, int]]:
    """
    Scans a sequence or mapping of objects with a 'role' attribute and identifies user/assistant message pairs.
    A pair is defined as a user message at index 'i' followed by an assistant message at index 'i+1'.
    Returns a list of (user_index, assistant_index) tuples using keys/indices.
    """
    pairs: list[tuple[int, int]] = []

    match history:
        case Mapping() as h_map:
            # Find pairs in sparse mapping based on key adjacency
            sorted_keys = sorted(h_map)
            # We only iterate indices where BOTH i and i+1 exist and form a pair
            for i in sorted_keys:
                match h_map.get(i), h_map.get(i + 1):
                    case HasRole(role="user"), HasRole(role="assistant"):
                        pairs.append((i, i + 1))
                    case _:
                        pass
        case Sequence() as h_seq:
            # Fallback for standard sequence
            idx = 0
            while idx < len(h_seq) - 1:
                match h_seq[idx], h_seq[idx + 1]:
                    case HasRole(role="user"), HasRole(role="assistant"):
                        pairs.append((idx, idx + 1))
                        idx += 2  # Move to the next potential pair
                    case _:
                        idx += 1
    return pairs


def find_message_pairs(chat_history: Sequence[HasRole] | Mapping[int, HasRole]) -> list[MessagePairIndices]:
    """
    Wrapper around the generic pair finder for ChatMessageHistoryItem lists or dicts.
    """
    positions = _generic_find_message_pairs(chat_history)
    return [MessagePairIndices(user_index=u, assistant_index=a) for u, a in positions]


def find_message_pairs_from_records(records: Sequence[HasRole]) -> list[tuple[int, int]]:
    """
    Wrapper around the generic pair finder for HistoryRecord-like lists.
    """
    return _generic_find_message_pairs(records)


def map_history_start_index_to_pair(
    chat_history: Sequence[HasRole] | Mapping[int, HasRole], history_start_index: int
) -> int:
    """
    Map a legacy message-centric history_start_index to a pair index.

    Returns the index of the first pair whose user message index is >= history_start_index.
    If history_start_index is beyond the end of the history, returns len(pairs).
    """
    pairs = find_message_pairs(chat_history)
    if not pairs:
        return 0

    # Calculate end of history based on type
    match chat_history:
        case Mapping() as h_map:
            end_bound = max(h_map, default=-1) + 1
        case Sequence() as h_seq:
            end_bound = len(h_seq)

    if history_start_index >= end_bound:
        return len(pairs)

    for pair_idx, p in enumerate(pairs):
        if p.user_index >= history_start_index:
            return pair_idx
    return len(pairs)
