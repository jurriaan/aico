"""
Phase 4 of the historystore package.

Provides:
- Data models for HistoryRecord and SessionView
- Sharded, append-only HistoryStore for immutable message persistence
- SessionView I/O and reconstruction helpers
- Edit / append / fork utilities
- Migration helpers (legacy <-> sharded view)
"""

from aico.lib.models import Mode

from .history_store import HistoryStore
from .migration import (
    deserialize_assistant_record,
    deserialize_user_record,
    from_legacy_session,
    reconstruct_chat_history,
    reconstruct_full_chat_history,
    to_legacy_session,
)
from .models import (
    SHARD_SIZE,
    HistoryRecord,
    SessionView,
    dumps_history_record,
    load_history_record,
)
from .session_view import (
    append_pair_to_view,
    edit_message,
    find_message_pairs_in_view,
    fork_view,
    load_view,
    save_view,
    switch_active_pointer,
)

__all__ = [
    "SHARD_SIZE",
    "Mode",
    "HistoryRecord",
    "SessionView",
    "dumps_history_record",
    "load_history_record",
    "HistoryStore",
    "load_view",
    "save_view",
    "find_message_pairs_in_view",
    "edit_message",
    "append_pair_to_view",
    "fork_view",
    "switch_active_pointer",
    "from_legacy_session",
    "to_legacy_session",
    "deserialize_user_record",
    "deserialize_assistant_record",
    "reconstruct_chat_history",
    "reconstruct_full_chat_history",
]
