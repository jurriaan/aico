import os
from pathlib import Path

import typer
from msgspec import Struct

from aico.consts import SESSION_FILE_NAME
from aico.exceptions import (
    ConfigurationError,
    InvalidInputError,
    SessionError,
    SessionIntegrityError,
)
from aico.history_utils import find_message_pairs
from aico.historystore import (
    HistoryStore,
    SessionView,
    append_pair_to_view,
    load_view,
    reconstruct_chat_history,
    save_view,
)
from aico.historystore import (
    edit_message as edit_message_historystore,
)
from aico.historystore.models import HistoryRecord
from aico.historystore.pointer import (
    InvalidPointerError,
    MissingViewError,
    load_pointer,
)
from aico.models import (
    ActiveContext,
    AssistantChatMessage,
    ChatMessageHistoryItem,
    MessagePairIndices,
    SessionData,
    UserChatMessage,
)

# === From session_find.py ===


def find_session_file() -> Path | None:
    if env_path := os.environ.get("AICO_SESSION_FILE"):
        path = Path(env_path)
        if not path.is_absolute():
            raise ConfigurationError("AICO_SESSION_FILE must be an absolute path")
        if not path.exists():
            raise ConfigurationError(f"Session file specified in AICO_SESSION_FILE does not exist: {path}")
        return path

    current = Path.cwd()
    for parent in [current, *current.parents]:
        check = parent / SESSION_FILE_NAME
        if check.is_file():
            return check
    return None


def complete_files_in_context(ctx: typer.Context | None, args: list[str], incomplete: str) -> list[str]:  # pyright: ignore[reportUnusedParameter]
    session_file = find_session_file()
    if not session_file:
        return []

    context_files: list[str] = []

    try:
        view_path = load_pointer(session_file)
        view_data = load_view(view_path)
        context_files = view_data.context_files
    except (InvalidPointerError, MissingViewError, OSError, Exception):
        return []

    return [f for f in context_files if f.startswith(incomplete)]


# === From session_context.py ===


def _normalize_index(index_str: str, num_pairs: int, allow_past_end: bool) -> int:
    try:
        index_val = int(index_str)
    except ValueError as e:
        raise InvalidInputError(f"Invalid index '{index_str}'. Must be an integer.") from e

    resolved_index = index_val

    if num_pairs == 0:
        if index_val == 0:
            return 0
        else:
            raise InvalidInputError("No message pairs found. The only valid index is 0.")

    if resolved_index < 0:
        resolved_index += num_pairs

    max_valid_index = num_pairs if allow_past_end else num_pairs - 1

    if 0 <= resolved_index <= max_valid_index:
        return resolved_index
    else:
        if num_pairs == 1:
            valid_range_str = "0 (or -1)"
            if allow_past_end:
                valid_range_str += f", or {num_pairs} to clear context"
        else:
            valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
            if allow_past_end:
                valid_range_str += f", or {num_pairs} to clear context"
        err_msg = f"Index out of bounds. Valid indices are in the range {valid_range_str}."
        raise InvalidInputError(err_msg)


def resolve_start_pair_index(pair_index_str: str, num_pairs: int) -> int:
    return _normalize_index(pair_index_str, num_pairs, allow_past_end=True)


def get_active_message_pairs(session_data: SessionData) -> list[tuple[int, MessagePairIndices]]:
    history = session_data.chat_history
    all_pairs_relative = find_message_pairs(history)

    start_pair_threshold = session_data.history_start_pair
    offset = session_data.offset

    active_pairs: list[tuple[int, MessagePairIndices]] = []

    for rel_idx, pair in enumerate(all_pairs_relative):
        abs_idx = rel_idx + offset
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
        rel_start_pair = start_pair_threshold - offset
        if rel_start_pair <= 0:
            start_msg_idx = 0
        elif rel_start_pair < len(pairs):
            start_msg_idx = pairs[rel_start_pair].user_index
        else:
            start_msg_idx = len(history)

        pair_positions = {pos for p in pairs for pos in (p.user_index, p.assistant_index)}

        for i in range(start_msg_idx, len(history)):
            if i not in pair_positions:
                valid_indices.append(i)

    return sorted(valid_indices)


def is_pair_excluded(session_data: SessionData, pair_index: int) -> bool:
    return pair_index in set(session_data.excluded_pairs)


class ActiveWindowSummary(Struct):
    active_pairs: int
    active_start_id: int
    active_end_id: int
    excluded_in_window: int
    pairs_sent: int
    has_active_dangling: bool
    has_any_active_history: bool


def summarize_active_window(session_data: SessionData) -> ActiveWindowSummary | None:
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


def _get_active_history(session_data: SessionData) -> list[ChatMessageHistoryItem]:
    indices = active_message_indices(session_data, include_dangling=True)
    return [session_data.chat_history[i] for i in indices]


def build_active_context(session_data: SessionData) -> ActiveContext:
    return {
        "model": session_data.model,
        "context_files": list(session_data.context_files),
        "active_history": _get_active_history(session_data),
    }


# === Unified Session Logic ===


class Session:
    """
    Represents the active session (file, data, and persistence operations).
    Replaces ActiveSession and SharedHistoryPersistence.
    """

    file_path: Path
    root: Path
    data: SessionData

    _view_path_abs: Path | None = None

    def __init__(self, file_path: Path, data: SessionData):
        self.file_path = file_path
        self.root = file_path.parent
        self.data = data

    @classmethod
    def load_active(cls) -> "Session":
        session_file = find_session_file()
        if not session_file:
            # We treat this as a user error for most commands
            raise SessionError(f"No session file '{SESSION_FILE_NAME}' found.")

        try:
            raw_text = session_file.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise SessionError(f"Could not read session file {session_file}: {e}") from e

        if not raw_text:
            raise SessionIntegrityError(f"Session file '{SESSION_FILE_NAME}' is empty.")

        if "aico_session_pointer_v1" not in raw_text:
            raise SessionIntegrityError(
                f"Detected a legacy session file at {session_file}.\n"
                + "This version of aico only supports the Shared History format.\n"
                + "Please run 'aico migrate-shared-history' to upgrade your project."
            )

        # Basic Check
        try:
            _ = load_pointer(session_file)
        except (MissingViewError, InvalidPointerError) as e:
            raise SessionIntegrityError(str(e)) from e

        instance = cls(session_file, SessionData(model="placeholder"))  # Temporary data holder

        # Now perform the actual load logic
        instance._load()
        return instance

    def _load(self) -> None:
        store, view = self._load_view_and_store()

        # Load the history window (from history_start_pair onwards)
        chat_history = reconstruct_chat_history(store, view, include_excluded=True)
        offset = view.history_start_pair

        self.data = SessionData(
            model=view.model,
            context_files=list(view.context_files),
            chat_history=chat_history,
            history_start_pair=view.history_start_pair,
            excluded_pairs=list(view.excluded_pairs),
            offset=offset,
        )

    def _load_view_and_store(self) -> tuple[HistoryStore, SessionView]:
        if self._view_path_abs is None:
            self._view_path_abs = load_pointer(self.file_path)

        store = HistoryStore(self.history_root)
        try:
            view = load_view(self._view_path_abs)
        except Exception as e:
            # This really shouldn't happen if validation passed, but safety first
            raise SessionError(f"Failed to load session view referenced by pointer ({self._view_path_abs}): {e}") from e
        return store, view

    @property
    def view_path(self) -> Path:
        if self._view_path_abs is None:
            self._view_path_abs = load_pointer(self.file_path)
        return self._view_path_abs

    @property
    def history_root(self) -> Path:
        return self.root / ".aico" / "history"

    @property
    def sessions_dir(self) -> Path:
        return self.root / ".aico" / "sessions"

    def get_view_path(self, name: str) -> Path:
        return self.sessions_dir / f"{name}.json"

    @property
    def num_pairs(self) -> int:
        """Returns the total number of message pairs in the session."""
        _, view = self._load_view_and_store()
        return len(view.message_indices) // 2

    def get_indices_if_loaded(self, resolved_index: int) -> MessagePairIndices | None:
        """Returns the relative MessagePairIndices if the pair is already in the chat_history cache."""
        pairs_in_window = find_message_pairs(self.data.chat_history)
        rel_index = resolved_index - self.data.offset

        if 0 <= rel_index < len(pairs_in_window):
            return pairs_in_window[rel_index]
        return None

    def fetch_pair(self, resolved_index: int) -> MessagePairIndices:
        """Surgically fetches a specific pair into the chat_history cache and returns its relative indices."""
        store, view = self._load_view_and_store()

        u_global_idx = view.message_indices[resolved_index * 2]
        a_global_idx = view.message_indices[resolved_index * 2 + 1]

        records = store.read_many([u_global_idx, a_global_idx])

        from aico.historystore.reconstruct import (
            deserialize_assistant_record,
            deserialize_user_record,
        )

        user_msg = deserialize_user_record(records[0])
        asst_msg = deserialize_assistant_record(records[1], view.model)

        # Update session data to reflect the fetched pair.
        self.data.chat_history = [user_msg, asst_msg]
        self.data.offset = resolved_index

        return MessagePairIndices(user_index=0, assistant_index=1)

    # Persistence Methods (from SharedHistoryPersistence)

    def append_pair(self, user_msg: UserChatMessage, asst_msg: AssistantChatMessage) -> None:
        store = HistoryStore(self.history_root)
        view = load_view(self.view_path)

        user_record = HistoryRecord.from_user_message(user_msg)
        assistant_record = HistoryRecord.from_assistant_message(asst_msg)
        _ = append_pair_to_view(store, view, user_record, assistant_record)

        save_view(self.view_path, view)

    def edit_message(
        self,
        message_index: int,
        new_content: str,
        new_metadata: AssistantChatMessage | None = None,
    ) -> None:
        store = HistoryStore(self.history_root)
        view = load_view(self.view_path)

        if not (0 <= message_index < len(view.message_indices)):
            raise SessionError("Edited message index out of bounds for current view.")

        original_msg_idx = view.message_indices[message_index]
        old_record = store.read_many([original_msg_idx])[0]

        if new_metadata:
            final_model = new_metadata.model
            final_derived = new_metadata.derived
            final_token_usage = new_metadata.token_usage
            final_cost = new_metadata.cost
            final_duration_ms = new_metadata.duration_ms
        else:
            final_model = old_record.model
            final_derived = None
            final_token_usage = None
            final_cost = None
            final_duration_ms = old_record.duration_ms

        new_record = HistoryRecord(
            role=old_record.role,
            content=new_content,
            mode=old_record.mode,
            timestamp=old_record.timestamp,
            model=final_model,
            duration_ms=final_duration_ms,
            derived=final_derived,
            token_usage=final_token_usage,
            cost=final_cost,
            passthrough=old_record.passthrough,
            piped_content=old_record.piped_content,
            edit_of=original_msg_idx,
        )

        _ = edit_message_historystore(store, view, message_index, new_record)
        save_view(self.view_path, view)

    def update_view_metadata(
        self,
        *,
        context_files: list[str] | None = None,
        model: str | None = None,
        history_start_pair: int | None = None,
        excluded_pairs: list[int] | None = None,
    ) -> None:
        view = load_view(self.view_path)
        changed = False

        if context_files is not None and view.context_files != context_files:
            view.context_files = sorted(context_files)
            changed = True
        if model is not None and view.model != model:
            view.model = model
            changed = True
        if history_start_pair is not None and view.history_start_pair != history_start_pair:
            view.history_start_pair = history_start_pair
            changed = True
        if excluded_pairs is not None and sorted(view.excluded_pairs) != sorted(excluded_pairs):
            view.excluded_pairs = sorted(excluded_pairs)
            changed = True

        if changed:
            save_view(self.view_path, view)


# === From session_loader.py (Index Helpers) ===


def expand_index_ranges(indices: list[str]) -> list[str]:
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
                if (start < 0) != (end < 0):
                    expanded.append(item)
                    continue
                step = 1 if start <= end else -1
                expanded.extend(str(i) for i in range(start, end + step, step))
            except ValueError:
                expanded.append(item)
        else:
            expanded.append(item)

    return expanded


def resolve_pair_index(index_str: str, num_pairs: int) -> int:
    if num_pairs == 0:
        raise InvalidInputError("No message pairs found in history.")

    return _normalize_index(index_str, num_pairs, allow_past_end=False)


def load_session_and_resolve_indices(index_str: str) -> tuple[Session, MessagePairIndices, int]:
    # 1. Load active session metadata without reconstructing history yet
    session = Session.load_active()

    # 2. Resolve the user's requested index using metadata
    resolved_index = resolve_pair_index(index_str, session.num_pairs)

    # 3. Check if the pair is already in the (windowed) chat_history
    if (pair_indices := session.get_indices_if_loaded(resolved_index)) is not None:
        return session, pair_indices, resolved_index

    # 4. Surgical Fetch: retrieve specifically the required messages
    pair_indices = session.fetch_pair(resolved_index)

    return session, pair_indices, resolved_index


def modify_pair_exclusions(raw_indices: list[str] | None, exclude: bool) -> list[int]:
    if not raw_indices:
        raw_indices = ["-1"]

    # 1. Expand ranges
    expanded_indices = expand_index_ranges(raw_indices)

    session = Session.load_active()

    # 2. Resolve total pairs and then all indices first
    num_pairs = session.num_pairs

    resolved_indices: list[int] = []
    for idx_str in expanded_indices:
        resolved_indices.append(resolve_pair_index(idx_str, num_pairs))

    # Use set operations for cleaner logic
    targets = set(resolved_indices)
    current_excluded = set(session.data.excluded_pairs)

    if exclude:
        changed_set = targets - current_excluded
        new_excluded = current_excluded | targets
    else:
        changed_set = targets & current_excluded
        new_excluded = current_excluded - targets

    actually_changed_sorted = sorted(changed_set)

    if actually_changed_sorted:
        session.update_view_metadata(excluded_pairs=sorted(new_excluded))

    return actually_changed_sorted
