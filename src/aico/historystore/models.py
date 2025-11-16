from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator
from pydantic.dataclasses import dataclass

from aico.lib.models import DerivedContent, Mode, TokenUsage, UserDerivedMeta

SHARD_SIZE = 10_000


@dataclass(slots=True, frozen=True)
class UserMetaEnvelope:
    aico_user_meta: UserDerivedMeta


type HistoryDerived = DerivedContent | UserMetaEnvelope


@dataclass(slots=True, frozen=True)
class HistoryRecord:
    """
    Immutable representation of a single message (user or assistant).

    Global index assignment and sharded persistence happen outside this model.
    Serialization guarantees a single JSON line; embedded newlines in content are
    escaped by JSON encoding and therefore safe.
    """

    role: Literal["user", "assistant"]
    content: str
    mode: Mode
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Assistant-only optional metadata
    model: str | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None
    duration_ms: int | None = None
    derived: HistoryDerived | None = None  # Structured envelope for user or assistant metadata

    # Edit lineage (stores global index of predecessor)
    edit_of: int | None = None


class SessionView(BaseModel):
    """
    Lightweight view/branch descriptor referencing global message indices.

    message_indices: ordered list of global indices into shards
    history_start_pair: pair boundary for active window logic (future phases)
    excluded_pairs: pair indices excluded from context (future logic)
    """

    model: str
    context_files: list[str] = Field(default_factory=list)
    message_indices: list[int] = Field(default_factory=list)
    history_start_pair: int = 0
    excluded_pairs: list[int] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @model_validator(mode="after")
    def _validate_indices(self) -> SessionView:
        if any(i < 0 for i in self.message_indices):
            raise ValueError("SessionView.message_indices must contain only non-negative integers.")
        if self.history_start_pair < 0:
            raise ValueError("SessionView.history_start_pair must be non-negative.")
        if any(i < 0 for i in self.excluded_pairs):
            raise ValueError("SessionView.excluded_pairs must contain only non-negative integers.")
        return self


def dumps_history_record(record: HistoryRecord) -> str:
    """
    Compact single-line JSON for a HistoryRecord.
    """
    return TypeAdapter(HistoryRecord).dump_json(record, indent=None, exclude_none=True).decode()


def load_history_record(line: str) -> HistoryRecord:
    """
    Parse a JSON line into a HistoryRecord.
    """
    return TypeAdapter(HistoryRecord).validate_json(line)
