import sys
from dataclasses import dataclass, replace

import typer

from aico.lib.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    MessagePairIndices,
    SessionData,
    UserChatMessage,
)


def find_message_pairs(chat_history: list[ChatMessageHistoryItem]) -> list[MessagePairIndices]:
    """
    Scans the chat history and identifies user/assistant message pairs.

    A pair is defined as a user message followed immediately by an assistant message.
    """
    pairs: list[MessagePairIndices] = []
    i = 0
    while i < len(chat_history) - 1:
        current_msg = chat_history[i]
        next_msg = chat_history[i + 1]
        if isinstance(current_msg, UserChatMessage) and isinstance(next_msg, AssistantChatMessage):
            pairs.append(MessagePairIndices(user_index=i, assistant_index=i + 1))
            i += 2  # Move to the next potential pair
        else:
            i += 1
    return pairs


def resolve_pair_index_to_message_indices(
    chat_history: list[ChatMessageHistoryItem], pair_index: int
) -> MessagePairIndices:
    """
    Resolves a human-friendly pair index (positive from start, negative from end)
    to a `MessagePairIndices` object containing the actual list indices.
    """
    pairs = find_message_pairs(chat_history)
    num_pairs = len(pairs)

    try:
        return pairs[pair_index]
    except IndexError:
        if not pairs:
            raise IndexError("Error: No message pairs found in history.") from None

        if num_pairs == 1:
            raise IndexError(
                f"Error: Pair at index {pair_index} not found. The only valid index is 0 (or -1)."
            ) from None

        valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
        raise IndexError(f"Error: Pair at index {pair_index} not found. Valid indices are {valid_range_str}.") from None


def resolve_history_start_index(chat_history: list[ChatMessageHistoryItem], pair_index_str: str) -> tuple[int, int]:
    """
    Resolves the start index for active history based on a human-friendly pair index string.

    Returns a tuple of (target_message_index, resolved_pair_index).
    """
    try:
        pair_index_val = int(pair_index_str)
    except ValueError:
        print(f"Error: Invalid index '{pair_index_str}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    pairs = find_message_pairs(chat_history)
    num_pairs = len(pairs)
    resolved_index = pair_index_val

    if num_pairs == 0:
        if pair_index_val == 0:
            target_message_index = 0
        else:
            print("Error: No message pairs found. The only valid index is 0.", file=sys.stderr)
            raise typer.Exit(code=1)
    elif -num_pairs <= pair_index_val < num_pairs:
        if resolved_index < 0:
            resolved_index += num_pairs
        target_message_index = pairs[pair_index_val].user_index
    elif pair_index_val == num_pairs:
        target_message_index = len(chat_history)
    else:
        if num_pairs == 1:
            err_msg = "Error: Index out of bounds. Valid index is 0 (or -1), or 1 to clear context."
        else:
            valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
            err_msg = (
                f"Error: Index out of bounds. Valid indices are in the range {valid_range_str}, "
                f"or {num_pairs} to clear context."
            )
        print(err_msg, file=sys.stderr)
        raise typer.Exit(code=1)

    return target_message_index, resolved_index


def is_pair_excluded(session_data: SessionData, pair_indices: MessagePairIndices) -> bool:
    """
    Returns True if the pair is excluded.
    - If `excluded_pairs` is populated, it is the source of truth.
    - Otherwise, falls back to per-message `is_excluded` flags for backward compatibility.
    """
    history = session_data.chat_history
    excluded_pairs_list: list[int] = session_data.excluded_pairs

    # If the pair-centric list exists and is not empty, use it as the source of truth.
    if excluded_pairs_list:
        pairs = find_message_pairs(history)
        try:
            pair_idx = next(i for i, p in enumerate(pairs) if p.user_index == pair_indices.user_index)
            return pair_idx in set(excluded_pairs_list)
        except StopIteration:
            return False

    # Fallback for legacy SessionData objects or empty exclusion lists
    user_msg = history[pair_indices.user_index]
    assistant_msg = history[pair_indices.assistant_index]
    return user_msg.is_excluded and assistant_msg.is_excluded


def set_pair_excluded(session_data: SessionData, pair_indices: MessagePairIndices, excluded: bool) -> bool:
    """
    Sets exclusion for a pair.
    - Canonical: updates session_data.excluded_pairs
    - Compatibility: also sets per-message is_excluded flags
    Returns True if any change was made.
    """
    changed = False

    # Update pair-centric list
    pairs = find_message_pairs(session_data.chat_history)
    try:
        pair_idx = next(
            i
            for i, p in enumerate(pairs)
            if p.user_index == pair_indices.user_index and p.assistant_index == pair_indices.assistant_index
        )
    except StopIteration:
        pair_idx = None

    if pair_idx is not None:
        current = set(getattr(session_data, "excluded_pairs", []) or [])
        if excluded and pair_idx not in current:
            current.add(pair_idx)
            session_data.excluded_pairs = sorted(current)
            changed = True
        elif not excluded and pair_idx in current:
            current.remove(pair_idx)
            session_data.excluded_pairs = sorted(current)
            changed = True

    # Update message-level flags for compatibility
    user_msg = session_data.chat_history[pair_indices.user_index]
    if user_msg.is_excluded != excluded:
        session_data.chat_history[pair_indices.user_index] = replace(user_msg, is_excluded=excluded)
        changed = True

    assistant_msg = session_data.chat_history[pair_indices.assistant_index]
    if assistant_msg.is_excluded != excluded:
        session_data.chat_history[pair_indices.assistant_index] = replace(assistant_msg, is_excluded=excluded)
        changed = True

    return changed


@dataclass(slots=True)
class InMemorySession:
    """
    Thin wrapper to host caches around SessionData.
    For Phase A, we keep it minimal and backward-compatible.
    """

    data: SessionData
    _pairs_cache: list[MessagePairIndices] | None = None

    def pairs(self) -> list[MessagePairIndices]:
        if self._pairs_cache is None:
            self._pairs_cache = find_message_pairs(self.data.chat_history)
        return self._pairs_cache

    def invalidate_pairs(self) -> None:
        self._pairs_cache = None


def active_message_indices(session_data: SessionData, include_dangling: bool = True) -> list[int]:
    """
    Compute active message indices for the current session based on:
      - history_start_pair for pairs (canonical)
      - excluded_pairs for pair exclusion (canonical)
      - history_start_index for dangling messages (legacy compatibility)
      - per-message is_excluded flags (for legacy/edge cases)
    """
    history = session_data.chat_history
    if not history:
        return []

    pairs = find_message_pairs(history)
    excluded_pairs: set[int] = set(session_data.excluded_pairs)

    active_positions: set[int] = set()

    # If there are pairs, include those at/after history_start_pair, minus exclusions
    if pairs:
        start_pair = max(0, int(getattr(session_data, "history_start_pair", 0)))
        # Map start pair beyond end to "empty window" for pairs
        if start_pair < len(pairs):
            for pidx, p in enumerate(pairs):
                if pidx < start_pair:
                    continue
                # Canonical exclusion by pair list, with legacy fallback to per-message flags
                user_ex = history[p.user_index].is_excluded
                asst_ex = history[p.assistant_index].is_excluded
                pair_is_excluded = (pidx in excluded_pairs) or (user_ex and asst_ex)
                if not pair_is_excluded:
                    active_positions.add(p.user_index)
                    active_positions.add(p.assistant_index)

    if not include_dangling:
        return sorted(active_positions)

    # Add dangling messages at/after the legacy start boundary
    start_boundary_dangling = int(getattr(session_data, "history_start_index", 0))
    pair_positions: set[int] = {pos for pp in pairs for pos in (pp.user_index, pp.assistant_index)}
    for i in range(start_boundary_dangling, len(history)):
        if i in pair_positions:
            continue
        if history[i].is_excluded:
            continue
        active_positions.add(i)

    return sorted(active_positions)


def map_history_start_index_to_pair(chat_history: list[ChatMessageHistoryItem], history_start_index: int) -> int:
    """
    Map a legacy message-centric history_start_index to a pair index.
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


@dataclass(slots=True)
class ActiveWindowSummary:
    active_pairs: int
    active_start_id: int
    active_end_id: int
    excluded_in_window: int
    pairs_sent: int
    has_active_dangling: bool
    has_any_active_history: bool


def summarize_active_window(session_data: SessionData) -> ActiveWindowSummary | None:
    """
    Produce a summary of the active window for status/log style displays.
    Returns None if there is no active history at all.
    """
    history = session_data.chat_history
    if not history:
        return None

    pairs = find_message_pairs(history)
    start_pair = getattr(session_data, "history_start_pair", 0)
    active_pairs_with_indices = [(pidx, p) for pidx, p in enumerate(pairs) if pidx >= start_pair]

    # Active dangling detection
    dangling_indices: set[int] = set(range(len(history)))
    pair_positions: set[int] = {pos for p in pairs for pos in (p.user_index, p.assistant_index)}
    dangling_indices = {i for i in range(len(history)) if i not in pair_positions}
    active_indices = set(active_message_indices(session_data, include_dangling=True))
    active_dangling = [i for i in dangling_indices if i in active_indices]

    if not active_pairs_with_indices and not active_dangling:
        return None

    excluded_set: set[int] = set(getattr(session_data, "excluded_pairs", []) or [])
    excluded_in_window = sum(1 for pidx, _ in active_pairs_with_indices if pidx in excluded_set) if excluded_set else 0

    active_window_pairs = len(active_pairs_with_indices)
    if active_pairs_with_indices:
        active_start_id = active_pairs_with_indices[0][0]
        active_end_id = active_pairs_with_indices[-1][0]
    else:
        active_start_id = 0
        active_end_id = 0

    pairs_sent = active_window_pairs - excluded_in_window
    return ActiveWindowSummary(
        active_pairs=active_window_pairs,
        active_start_id=active_start_id,
        active_end_id=active_end_id,
        excluded_in_window=excluded_in_window,
        pairs_sent=pairs_sent,
        has_active_dangling=bool(active_dangling),
        has_any_active_history=True,
    )
