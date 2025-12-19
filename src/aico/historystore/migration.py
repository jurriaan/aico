from __future__ import annotations

from pathlib import Path
from typing import Literal

import msgspec
from msgspec import Struct, field

from aico.models import (
    DerivedContent,
    Mode,
    TokenUsage,
)

from .history_store import HistoryStore
from .models import HistoryRecord, SessionView
from .session_view import save_view

# --- Legacy Schemas (Migration Source) ---


class LegacyUserChatMessage(msgspec.Struct, tag="user", tag_field="role"):
    content: str
    mode: Mode
    timestamp: str
    piped_content: str | None = None
    passthrough: bool = False
    is_excluded: bool = False

    @property
    def role(self) -> Literal["user"]:
        return "user"


class LegacyAssistantChatMessage(msgspec.Struct, tag="assistant", tag_field="role"):
    content: str
    mode: Mode
    timestamp: str
    model: str
    duration_ms: int
    derived: DerivedContent | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None
    is_excluded: bool = False

    @property
    def role(self) -> Literal["assistant"]:
        return "assistant"


type LegacyChatMessage = LegacyUserChatMessage | LegacyAssistantChatMessage


class LegacySessionSnapshot(Struct):
    model: str
    context_files: list[str] = field(default_factory=list)
    chat_history: list[LegacyChatMessage] = field(default_factory=list)
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
    # and these Struct models have it.
    from aico.history_utils import find_message_pairs

    # During migration, we iterate the legacy list and append to sharded store
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
    # Using find_message_pairs to get pairs from legacy message list.
    pairs_idx = find_message_pairs(session_data.chat_history)

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
