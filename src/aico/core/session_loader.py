import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import typer

from aico.core.session_persistence import (
    SharedHistoryPersistence,
    StatefulSessionPersistence,
    get_persistence,
)
from aico.lib.history_utils import find_message_pairs
from aico.lib.models import MessagePairIndices, SessionData


@dataclass(frozen=True, slots=True)
class ActiveSession:
    persistence: StatefulSessionPersistence
    file_path: Path
    data: SessionData
    root: Path


def load_active_session(
    full_history: bool = False,
    require_type: Literal["any", "shared"] = "any",
) -> ActiveSession:
    persistence = get_persistence(require_type=require_type)

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

    try:
        user_idx_val = int(index_str)
    except ValueError:
        print(f"Error: Invalid index '{index_str}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    pairs = find_message_pairs(session.data.chat_history)
    num_pairs = len(pairs)

    if num_pairs == 0:
        print("Error: No message pairs found in history.", file=sys.stderr)
        raise typer.Exit(code=1)

    # Map negative indices to their positive counterparts.
    if user_idx_val < 0:
        if user_idx_val < -num_pairs:
            if num_pairs == 1:
                err_msg = f"Error: Pair at index {user_idx_val} not found. The only valid index is 0 (or -1)."
            else:
                valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
                err_msg = f"Error: Pair at index {user_idx_val} not found. Valid indices are {valid_range_str}."
            print(err_msg, file=sys.stderr)
            raise typer.Exit(code=1)
        resolved_index = num_pairs + user_idx_val
    else:
        if user_idx_val >= num_pairs:
            if num_pairs == 1:
                err_msg = f"Error: Pair at index {user_idx_val} not found. The only valid index is 0 (or -1)."
            else:
                valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
                err_msg = f"Error: Pair at index {user_idx_val} not found. Valid indices are {valid_range_str}."
            print(err_msg, file=sys.stderr)
            raise typer.Exit(code=1)
        resolved_index = user_idx_val

    pair_indices = pairs[resolved_index]
    return session, pair_indices, resolved_index
