from dataclasses import dataclass
from pathlib import Path

from aico.exceptions import InvalidInputError
from aico.history_utils import find_message_pairs
from aico.models import MessagePairIndices, SessionData
from aico.session_persistence import (
    SharedHistoryPersistence,
    StatefulSessionPersistence,
    get_persistence,
)


@dataclass(frozen=True, slots=True)
class ActiveSession:
    persistence: StatefulSessionPersistence
    file_path: Path
    data: SessionData
    root: Path


def expand_index_ranges(indices: list[str]) -> list[str]:
    """
    Expands index strings into individual IDs, supporting Git-style ranges.

    Syntax:
      - Single: "1", "-1"
      - Range:  "start..end" (Inclusive on both ends)

    Constraint:
      Start and End must have the same sign to avoid ambiguous wrapping.

    Examples:
      - "1..3"    -> ["1", "2", "3"]  (Allowed)
      - "-3..-1"  -> ["-3", "-2", "-1"] (Allowed)
      - "1..-1"   -> ["1..-1"] (Ignored, treated as literal)
    """
    if not indices:
        return ["-1"]

    expanded: list[str] = []
    import regex

    range_pattern = regex.compile(r"^(-?\d+)\.\.(-?\d+)$")

    for item in indices:
        match = range_pattern.match(item)
        if match:
            start_str, end_str = match.groups()
            try:
                start, end = int(start_str), int(end_str)

                # ENFORCE SAME SIGN:
                # Check if one is negative and the other is non-negative.
                # Note: 0 is treated as non-negative.
                if (start < 0) != (end < 0):
                    # Mixed signs (e.g. 2..-2) are ambiguous without list length.
                    # Treat as literal (which will likely fail validation later).
                    expanded.append(item)
                    continue

                # Determine direction
                step = 1 if start <= end else -1

                # Inclusive range generation
                expanded.extend(str(i) for i in range(start, end + step, step))
            except ValueError:
                expanded.append(item)
        else:
            expanded.append(item)

    return expanded


def load_active_session(
    full_history: bool = False,
) -> ActiveSession:
    persistence = get_persistence()

    if full_history and isinstance(persistence, SharedHistoryPersistence):
        session_file, session_data = persistence.load_full_history()
    else:
        session_file, session_data = persistence.load()

    return ActiveSession(
        persistence=persistence,
        file_path=session_file,
        data=session_data,
        root=session_file.parent,
    )


def resolve_pair_index(session: ActiveSession, index_str: str) -> int:
    """
    Resolves a single user-provided index string against the loaded session.
    Returns the absolute pair index. Exits if invalid.
    """
    try:
        user_idx_val = int(index_str)
    except ValueError as e:
        raise InvalidInputError(f"Invalid index '{index_str}'. Must be an integer.") from e

    pairs = find_message_pairs(session.data.chat_history)
    num_pairs = len(pairs)

    if num_pairs == 0:
        raise InvalidInputError("No message pairs found in history.")

    # Map negative indices to their positive counterparts.
    if user_idx_val < 0:
        if user_idx_val < -num_pairs:
            if num_pairs == 1:
                err_msg = f"Pair at index {user_idx_val} not found. The only valid index is 0 (or -1)."
            else:
                valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
                err_msg = f"Pair at index {user_idx_val} not found. Valid indices are {valid_range_str}."
            raise InvalidInputError(err_msg)
        resolved_index = num_pairs + user_idx_val
    else:
        if user_idx_val >= num_pairs:
            if num_pairs == 1:
                err_msg = f"Pair at index {user_idx_val} not found. The only valid index is 0 (or -1)."
            else:
                valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
                err_msg = f"Pair at index {user_idx_val} not found. Valid indices are {valid_range_str}."
            raise InvalidInputError(err_msg)
        resolved_index = user_idx_val

    return resolved_index


def load_session_and_resolve_indices(
    index_str: str,
) -> tuple[ActiveSession, MessagePairIndices, int]:
    """
    Load the session (full history), parse a user-provided index string, and resolve it to
    a message pair using global pair indices.

    Supports:
      - Positive indices: 0..N-1 over the full history.
      - Negative indices: -1..-N counted from the end of the full history.
    """
    session = load_active_session(full_history=True)
    resolved_index = resolve_pair_index(session, index_str)

    pairs = find_message_pairs(session.data.chat_history)
    pair_indices = pairs[resolved_index]

    return session, pair_indices, resolved_index
