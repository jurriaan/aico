# pyright: standard
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from msgspec import Struct, field

from aico.models import (
    AssistantChatMessage,
    Mode,
    TokenUsage,
    UserChatMessage,
)
from aico.serialization import from_json, to_json

SHARD_SIZE = 10_000


class HistoryRecord(Struct, frozen=True):
    """
    Immutable representation of a single message (user or assistant).

    Global index assignment and sharded persistence happen outside this model.
    Serialization guarantees a single JSON line; embedded newlines in content are
    escaped by JSON encoding and therefore safe.
    """

    role: Literal["user", "assistant"]
    content: str
    mode: Mode
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    passthrough: bool = False
    piped_content: str | None = None

    # Assistant-only optional metadata
    model: str | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None
    duration_ms: int | None = None
    derived: object | None = None  # Use object to allow migration of legacy nested dicts

    # Edit lineage (stores global index of predecessor)
    edit_of: int | None = None

    def __post_init__(self) -> None:
        # Legacy user meta migration from when passthrough/piped_content were nested in 'derived'
        match self.role, self.derived:
            case "user", {"aico_user_meta": dict(meta)}:
                object.__setattr__(self, "passthrough", meta.get("passthrough", False))
                object.__setattr__(self, "piped_content", meta.get("piped_content"))
                object.__setattr__(self, "derived", None)
            case _:
                pass

    @classmethod
    def from_user_message(cls, msg: UserChatMessage) -> HistoryRecord:
        return cls(
            role="user",
            content=msg.content,
            mode=msg.mode,
            timestamp=msg.timestamp,
            passthrough=msg.passthrough,
            piped_content=msg.piped_content,
        )

    @classmethod
    def from_assistant_message(cls, msg: AssistantChatMessage) -> HistoryRecord:
        return cls(
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


class SessionView(Struct):
    """
    Lightweight view/branch descriptor referencing global message indices.

    message_indices: ordered list of global indices into shards
    history_start_pair: pair boundary for active window logic (future phases)
    excluded_pairs: pair indices excluded from context (future logic)
    """

    model: str
    context_files: list[str] = field(default_factory=list)
    message_indices: list[int] = field(default_factory=list)
    history_start_pair: int = 0
    excluded_pairs: list[int] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if any(i < 0 for i in self.message_indices):
            raise ValueError("SessionView.message_indices must contain only non-negative integers.")
        if self.history_start_pair < 0:
            raise ValueError("SessionView.history_start_pair must be non-negative.")
        if any(i < 0 for i in self.excluded_pairs):
            raise ValueError("SessionView.excluded_pairs must contain only non-negative integers.")


def dumps_history_record(record: HistoryRecord) -> str:
    """
    Compact single-line JSON for a HistoryRecord.
    """
    return to_json(record).decode("utf-8")


def load_history_record(line: str | bytes) -> HistoryRecord:
    """
    Parse a JSON line into a HistoryRecord.
    """
    return from_json(HistoryRecord, line)
