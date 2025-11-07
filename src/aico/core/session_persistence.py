import copy
import sys
from pathlib import Path
from typing import Protocol, runtime_checkable

import typer
from pydantic import ValidationError

from aico.core.session_context import (
    find_message_pairs,
    map_history_start_index_to_pair,
    resolve_pair_index_to_message_indices,
)
from aico.historystore import (
    HistoryStore,
    append_pair_to_view,
    edit_message,
    find_message_pairs_in_view,
    load_view,
    reconstruct_chat_history,
    save_view,
)
from aico.historystore.models import HistoryRecord, UserMetaEnvelope
from aico.historystore.pointer import SessionPointer
from aico.historystore.pointer import load_pointer as load_pointer_helper
from aico.lib.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    MessagePairIndices,
    SessionData,
    UserChatMessage,
    UserDerivedMeta,
)
from aico.lib.session import (
    find_session_file,
)
from aico.lib.session import (
    load_session as legacy_load_session,
)
from aico.lib.session import (
    save_session as legacy_save_session,
)


@runtime_checkable
class SessionPersistence(Protocol):
    def load(self) -> tuple[Path, SessionData]: ...
    def save(self, session_file: Path, session_data: SessionData) -> None: ...


class LegacyJsonPersistence:
    def load(self) -> tuple[Path, SessionData]:
        session_file, session_data = legacy_load_session()

        # --- In-memory upgrade for backward compatibility ---
        # Derive pair-centric fields from legacy message-centric fields to align
        # with new logic in `log`, `status`, and `get_active_history`.
        chat_history = session_data.chat_history
        pairs = find_message_pairs(chat_history)

        # Derive excluded_pairs from per-message flags
        excluded_from_messages = [
            idx
            for idx, p in enumerate(pairs)
            if chat_history[p.user_index].is_excluded and chat_history[p.assistant_index].is_excluded
        ]
        session_data.excluded_pairs = excluded_from_messages

        # Derive history_start_pair from history_start_index
        session_data.history_start_pair = map_history_start_index_to_pair(
            chat_history, session_data.history_start_index
        )

        return session_file, session_data

    def save(self, session_file: Path, session_data: SessionData) -> None:
        legacy_save_session(session_file, session_data)


class SharedHistoryPersistence:
    """
    Shared-history adapter with write support enabled by default.

    Supports:
      - Appending exactly one new user/assistant pair at the end.
      - Editing exactly one existing message.
      - Toggling exclusions (undo/redo).
      - Updating history start index.
      - Updating context files, model.
    Rejects ambiguous multi-edits or mid-list insertions.
    """

    _pointer_file: Path
    _session_root: Path
    _history_root: Path
    _view_rel_path: str | None
    _view_path_abs: Path | None
    _original_session: SessionData | None
    writable: bool

    def __init__(self, pointer_file: Path):
        self._pointer_file = pointer_file
        self._session_root = pointer_file.parent
        self._history_root = self._session_root / ".aico" / "history"
        self._view_rel_path = None
        self._view_path_abs = None
        self._original_session = None
        # Writes are enabled by default
        self.writable = True

    # ---------- Load ----------

    def load(self) -> tuple[Path, SessionData]:
        """
        Load the active SessionView and reconstruct a strongly-typed SessionData.
        """
        # Resolve and validate the session view path from the pointer file
        self._view_path_abs = load_pointer_helper(self._pointer_file)

        store = HistoryStore(self._history_root)
        try:
            view = load_view(self._view_path_abs)
        except Exception as e:
            typer.echo(
                f"Error: Failed to load session view referenced by pointer ({self._view_path_abs}): {e}",
                err=True,
            )
            raise typer.Exit(1) from e

        chat_history = reconstruct_chat_history(store, view)

        pair_positions = find_message_pairs_in_view(store, view)

        # Map history_start_pair -> history_start_index
        if view.history_start_pair >= len(pair_positions):
            history_start_index = len(chat_history)
        elif view.history_start_pair <= 0:
            history_start_index = 0
        else:
            history_start_index = pair_positions[view.history_start_pair][0]

        session_data = SessionData(
            model=view.model,
            context_files=list(view.context_files),
            chat_history=chat_history,
            history_start_index=history_start_index,
            history_start_pair=view.history_start_pair,
            excluded_pairs=list(view.excluded_pairs),
        )

        # Snapshot for diffing on save
        self._original_session = copy.deepcopy(session_data)
        return self._pointer_file, session_data

    # ---------- Save (Phase C logic) ----------

    def save(self, session_file: Path, session_data: SessionData) -> None:
        del session_file
        if not self.writable:
            typer.echo(
                "Error: This is a read-only shared-history session. Write commands are not yet supported.",
                err=True,
            )
            raise typer.Exit(code=1)

        if self._original_session is None or self._view_path_abs is None:
            typer.echo("Error: Internal state missing for shared-history save.", err=True)
            raise typer.Exit(code=1)

        store = HistoryStore(self._history_root)
        view = load_view(self._view_path_abs)

        original = self._original_session
        new = session_data

        # --- Detect operations ---
        original_len = len(original.chat_history)
        new_len = len(new.chat_history)

        appended_pair = False
        edited_message_index: int | None = None
        edited_message_new_content: str | None = None

        if new_len == original_len + 2:
            # Potential append
            if isinstance(new.chat_history[-2], UserChatMessage) and isinstance(
                new.chat_history[-1], AssistantChatMessage
            ):
                appended_pair = True
            else:
                self._fail("Ambiguous append: last two messages are not a user/assistant pair.")
        elif new_len == original_len:
            # Potential edit (exactly one content change)
            diffs = [
                i
                for i, (o_msg, n_msg) in enumerate(zip(original.chat_history, new.chat_history, strict=False))
                if o_msg.content != n_msg.content
            ]
            if len(diffs) == 1:
                edited_message_index = diffs[0]
                edited_message_new_content = new.chat_history[edited_message_index].content
            elif len(diffs) == 0:
                # No content diff; may only be exclusions / start index / context/model changes
                pass
            else:
                self._fail("Multiple message content edits detected. Perform edits one at a time.")
        else:
            self._fail(
                "Unsupported history mutation. Only single edits or a single appended pair are supported in this phase."
            )

        # --- Apply operations ---

        # 1. Append pair
        if appended_pair:
            user_msg = new.chat_history[-2]
            asst_msg = new.chat_history[-1]
            if isinstance(user_msg, UserChatMessage) and isinstance(asst_msg, AssistantChatMessage):
                # Validate append at end only
                if original_len != len(view.message_indices):
                    self._fail(
                        "Invariant mismatch: view/message_indices length does not match original history length."
                    )

                user_record = self._to_history_record_user(user_msg)
                assistant_record = self._to_history_record_assistant(asst_msg)
                _ = append_pair_to_view(store, view, user_record, assistant_record)

        # 2. Edit existing message
        if edited_message_index is not None and edited_message_new_content is not None:
            # Map message index to view position (same ordering)
            if not (0 <= edited_message_index < len(view.message_indices)):
                self._fail("Edited message index out of bounds for current view.")

            # Preserve derived/token/model on assistant edits when provided in new session_data
            new_msg = new.chat_history[edited_message_index]
            if isinstance(new_msg, AssistantChatMessage):
                _ = edit_message(
                    store,
                    view,
                    edited_message_index,
                    edited_message_new_content,
                    model=new_msg.model,
                    derived=new_msg.derived,
                    token_usage=new_msg.token_usage,
                    cost=new_msg.cost,
                    duration_ms=new_msg.duration_ms,
                )
            else:
                # User edit: keep metadata as-is
                _ = edit_message(store, view, edited_message_index, edited_message_new_content)

        # 3. Exclusion toggles
        if hasattr(new, "excluded_pairs"):
            view.excluded_pairs = sorted(set(new.excluded_pairs))
        else:
            new_excluded_pairs = self._compute_excluded_pairs(new.chat_history)
            view.excluded_pairs = new_excluded_pairs

        # 4. History start mapping
        if hasattr(new, "history_start_pair"):
            view.history_start_pair = int(new.history_start_pair)
        else:
            view.history_start_pair = map_history_start_index_to_pair(new.chat_history, new.history_start_index)

        # 5. Context files & model
        if original.context_files != new.context_files:
            view.context_files = sorted(new.context_files)
        if original.model != new.model:
            view.model = new.model

        # Invariants before persisting
        pairs_now = find_message_pairs(new.chat_history)
        assert len(view.message_indices) == len(new.chat_history), (
            "Invariant violation: view/message_indices length mismatch after save."
        )
        assert all(p < len(pairs_now) for p in view.excluded_pairs), (
            "Invariant violation: excluded pair index out of bounds."
        )

        # Persist view
        save_view(self._view_path_abs, view)
        # Update original snapshot for subsequent saves
        self._original_session = copy.deepcopy(new)

    # ---------- Helpers ----------

    def _fail(self, message: str) -> None:
        typer.echo(f"Error: {message}", err=True)
        raise typer.Exit(code=1)

    def _compute_excluded_pairs(self, chat_history: list[ChatMessageHistoryItem]) -> list[int]:
        pairs = find_message_pairs(chat_history)
        excluded: list[int] = []
        for idx, p in enumerate(pairs):
            if chat_history[p.user_index].is_excluded and chat_history[p.assistant_index].is_excluded:
                excluded.append(idx)
        return excluded

    def _compute_history_start_pair(self, chat_history: list[ChatMessageHistoryItem], history_start_index: int) -> int:
        return map_history_start_index_to_pair(chat_history, history_start_index)

    def _to_history_record_user(self, msg: UserChatMessage) -> HistoryRecord:
        derived_envelope: UserMetaEnvelope | None = None
        if msg.passthrough or msg.piped_content is not None:
            # Only include when non-default metadata is present
            user_meta = UserDerivedMeta(passthrough=msg.passthrough, piped_content=msg.piped_content)
            if user_meta.model_dump(exclude_defaults=True):
                derived_envelope = UserMetaEnvelope(aico_user_meta=user_meta)

        return HistoryRecord(
            role="user",
            content=msg.content,
            mode=msg.mode,
            timestamp=msg.timestamp,
            derived=derived_envelope,
        )

    def _to_history_record_assistant(self, msg: AssistantChatMessage) -> HistoryRecord:
        return HistoryRecord(
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


def load_session_and_resolve_indices(
    index_str: str,
    persistence: SessionPersistence | None = None,
) -> tuple[Path, SessionData, MessagePairIndices, int]:
    """
    Loads session (using provided persistence instance when supplied), parses index string,
    and resolves message pair indices.
    Supplying a persistence instance ensures commands perform load/save on the SAME
    persistence object (important for shared-history write tracking).
    """
    persistence = persistence or get_persistence()
    session_file, session_data = persistence.load()

    try:
        pair_index_int = int(index_str)
    except ValueError:
        print(f"Error: Invalid index '{index_str}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    try:
        pair_indices = resolve_pair_index_to_message_indices(session_data.chat_history, pair_index_int)
    except IndexError as e:
        print(str(e), file=sys.stderr)
        raise typer.Exit(code=1) from e

    resolved_index = pair_index_int
    if resolved_index < 0:
        all_pairs = find_message_pairs(session_data.chat_history)
        resolved_index += len(all_pairs)

    return session_file, session_data, pair_indices, resolved_index


def get_persistence() -> SessionPersistence:
    """
    Factory for persistence backend; detects pointer file to enable shared-history.
    """
    session_file_path = find_session_file()
    if session_file_path is None:
        return LegacyJsonPersistence()

    try:
        raw_text = session_file_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return LegacyJsonPersistence()
    except OSError:
        # File found but unreadable, let legacy loader handle it.
        return LegacyJsonPersistence()

    # Optimization: if it doesn't contain the magic string, it can't be a pointer.
    if "aico_session_pointer_v1" not in raw_text:
        return LegacyJsonPersistence()

    # At this point, it's likely a pointer. Let's verify with Pydantic.
    try:
        # We only try to validate as a pointer. If it fails, it's legacy.
        _ = SessionPointer.model_validate_json(raw_text)
        return SharedHistoryPersistence(session_file_path)
    except ValidationError:
        # It had the magic string but didn't validate as a pointer.
        # This could be a legacy session that happens to contain the string
        # in its content. Fall back to legacy.
        return LegacyJsonPersistence()
