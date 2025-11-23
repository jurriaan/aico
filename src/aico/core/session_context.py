import sys
from dataclasses import dataclass

import typer

from aico.lib.history_utils import find_message_pairs
from aico.lib.models import (
    ActiveContext,
    ChatMessageHistoryItem,
    MessagePairIndices,
    SessionData,
)


def resolve_start_pair_index(pair_index_str: str, num_pairs: int) -> int:
    """
    Resolves a human-friendly pair index string against a total number of pairs.
    Returns a resolved, non-negative, absolute pair index.
    """
    try:
        pair_index_val = int(pair_index_str)
    except ValueError as e:
        print(f"Error: Invalid index '{pair_index_str}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from e

    resolved_index = pair_index_val

    if num_pairs == 0:
        if pair_index_val == 0:
            return 0
        else:
            print("Error: No message pairs found. The only valid index is 0.", file=sys.stderr)
            raise typer.Exit(code=1)

    if -num_pairs <= resolved_index < num_pairs:
        if resolved_index < 0:
            resolved_index += num_pairs
        return resolved_index
    elif resolved_index == num_pairs:
        # This corresponds to 'clear'
        return num_pairs
    else:
        # Error condition
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


def get_active_message_pairs(session_data: SessionData) -> list[tuple[int, MessagePairIndices]]:
    """
    Returns the message pairs within the active window for display.

    This is the single source of truth for which pairs are included in the `log` command.
    - For shared-history sessions (pre-sliced history), it returns all pairs present,
      correcting their indices to be absolute for display.
    - For legacy sessions (full history), it applies filtering based on `history_start_pair`.
    """
    history = session_data.chat_history
    all_pairs_relative_to_history = find_message_pairs(history)
    all_pairs_with_relative_indices = list(enumerate(all_pairs_relative_to_history))

    # For pre-sliced histories (shared-history), `chat_history` already contains only the
    # active window. In this case, `history_start_pair` holds the absolute index of the
    # first pair in this slice. We must add this offset to our relative pair indices to
    # get correct absolute IDs for display in `log`.
    if session_data.is_pre_sliced:
        start_pair_offset = session_data.history_start_pair
        return [(pair_idx + start_pair_offset, pair) for pair_idx, pair in all_pairs_with_relative_indices]

    # For legacy sessions, `chat_history` is the full history. The pair indices are
    # already absolute. We just need to filter them from `history_start_pair` onwards.
    start_pair = session_data.history_start_pair
    active_pairs = [(pair_idx, pair) for pair_idx, pair in all_pairs_with_relative_indices if pair_idx >= start_pair]
    return active_pairs


def is_pair_excluded(session_data: SessionData, pair_index: int) -> bool:
    """
    Returns True if the absolute pair_index is in the set of excluded pairs.
    """
    return pair_index in set(session_data.excluded_pairs)


def get_start_message_index(session_data: SessionData) -> int:
    """Calculates the message index from the canonical history_start_pair."""
    # For pre-sliced/shared history, the history is already the active window, so
    # the start index for the current chat is always 0.
    if session_data.is_pre_sliced:
        return 0

    chat_history = session_data.chat_history
    history_start_pair = session_data.history_start_pair
    pairs = find_message_pairs(chat_history)

    if history_start_pair <= 0:
        return 0
    if history_start_pair >= len(pairs):
        return len(chat_history)

    return pairs[history_start_pair].user_index


def active_message_indices(session_data: SessionData, include_dangling: bool = True) -> list[int]:
    """
    Compute active message indices.
    - For shared-history sessions (pre-sliced history), it honors the `is_excluded`
      flag on messages that `reconstruct_chat_history` sets.
    - For legacy sessions, it uses `history_start_pair` and `excluded_pairs` to slice the full history.
    """
    history = session_data.chat_history
    if not history:
        return []

    if session_data.is_pre_sliced:
        # For shared history, history is pre-sliced. Exclusions are marked on messages.
        # This correctly includes non-excluded pairs and all dangling messages.
        active_indices_set = {i for i, msg in enumerate(history) if not msg.is_excluded}
        return sorted(list(active_indices_set))

    # For legacy sessions, the full history is loaded, so we must apply the filters.
    pairs = find_message_pairs(history)
    excluded_pairs_set: set[int] = set(session_data.excluded_pairs)
    active_positions: set[int] = set()
    start_pair = session_data.history_start_pair

    # Process pairs: Active if at/after `start_pair` and not excluded.
    for pidx, p in enumerate(pairs):
        if pidx < start_pair:
            continue

        if pidx in excluded_pairs_set:
            continue

        active_positions.add(p.user_index)
        active_positions.add(p.assistant_index)

    if not include_dangling:
        return sorted(list(active_positions))

    # Process dangling messages for legacy: they are active if they are in the active window.
    start_boundary_dangling = get_start_message_index(session_data)
    pair_positions: set[int] = {pos for p in pairs for pos in (p.user_index, p.assistant_index)}
    for msg_idx in range(start_boundary_dangling, len(history)):
        if msg_idx not in pair_positions:
            active_positions.add(msg_idx)

    return sorted(list(active_positions))


@dataclass(slots=True)
class ActiveWindowSummary:
    active_pairs: int
    active_start_id: int
    active_end_id: int
    excluded_in_window: int
    pairs_sent: int
    has_active_dangling: bool
    has_any_active_history: bool


def _get_active_history(session_data: SessionData) -> list[ChatMessageHistoryItem]:
    """
    Internal helper: Returns the active slice of chat history messages.
    """
    indices = active_message_indices(session_data, include_dangling=True)
    return [session_data.chat_history[i] for i in indices]


def build_active_context(session_data: SessionData) -> ActiveContext:
    """
    Builds the fully resolved runtime context from the session storage data.
    This is the main entry point for commands to access session state.
    """
    return {
        "model": session_data.model,
        "context_files": list(session_data.context_files),
        "active_history": _get_active_history(session_data),
    }


def summarize_active_window(session_data: SessionData) -> ActiveWindowSummary | None:
    """
    Produce a summary of the active window for status/log style displays.
    Returns None if there is no active history at all.
    """
    history = session_data.chat_history
    if not history:
        return None

    active_pairs_with_indices = get_active_message_pairs(session_data)

    # Active dangling detection
    all_pairs_in_history_list = find_message_pairs(history)
    all_paired_indices = {idx for p in all_pairs_in_history_list for idx in (p.user_index, p.assistant_index)}
    active_indices_set = set(active_message_indices(session_data, include_dangling=True))
    has_active_dangling = any(i not in all_paired_indices and i in active_indices_set for i in range(len(history)))

    if not active_pairs_with_indices and not has_active_dangling:
        return None

    excluded_set: set[int] = set(session_data.excluded_pairs)
    excluded_in_window = sum(1 for pidx, _ in active_pairs_with_indices if pidx in excluded_set)

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
        has_active_dangling=has_active_dangling,
        has_any_active_history=True,
    )
