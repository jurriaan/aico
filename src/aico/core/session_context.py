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
    history = session_data.chat_history
    all_pairs_relative = find_message_pairs(history)

    start_pair_threshold = session_data.history_start_pair
    offset = session_data.offset

    active_pairs: list[tuple[int, MessagePairIndices]] = []

    for rel_idx, pair in enumerate(all_pairs_relative):
        # Calculate absolute ID
        abs_idx = rel_idx + offset

        # Filter: In full history mode, this skips old messages.
        # In sliced mode, abs_idx is always >= start, so it keeps everything.
        if abs_idx >= start_pair_threshold:
            active_pairs.append((abs_idx, pair))

    return active_pairs


def active_message_indices(session_data: SessionData, include_dangling: bool = True) -> list[int]:
    history = session_data.chat_history
    if not history:
        return []

    pairs = find_message_pairs(history)
    valid_indices: list[int] = []
    excluded_set = set(session_data.excluded_pairs)

    start_pair_threshold = session_data.history_start_pair
    offset = session_data.offset

    # 1. Collect Valid Pairs
    for rel_pair_idx, p in enumerate(pairs):
        abs_pair_idx = rel_pair_idx + offset

        # Window Filter
        if abs_pair_idx < start_pair_threshold:
            continue

        # Exclusion Filter
        if abs_pair_idx in excluded_set:
            continue

        valid_indices.extend([p.user_index, p.assistant_index])

    if include_dangling:
        # Determine the local index where the active window starts
        rel_start_pair = start_pair_threshold - offset
        if rel_start_pair <= 0:
            start_msg_idx = 0
        elif rel_start_pair < len(pairs):
            start_msg_idx = pairs[rel_start_pair].user_index
        else:
            start_msg_idx = len(history)

        # Collect any message in the active window that isn't part of a pair
        # (This handles mid-stream dangling messages correctly)
        pair_positions = {pos for p in pairs for pos in (p.user_index, p.assistant_index)}

        for i in range(start_msg_idx, len(history)):
            if i not in pair_positions:
                valid_indices.append(i)

    return sorted(valid_indices)


def is_pair_excluded(session_data: SessionData, pair_index: int) -> bool:
    """
    Returns True if the absolute pair_index is in the set of excluded pairs.
    """
    return pair_index in set(session_data.excluded_pairs)


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
