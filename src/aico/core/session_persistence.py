from pathlib import Path
from typing import Protocol, runtime_checkable

import typer

from aico.consts import SESSION_FILE_NAME
from aico.exceptions import SessionError, SessionIntegrityError
from aico.historystore import (
    HistoryStore,
    append_pair_to_view,
    load_view,
    reconstruct_chat_history,
    reconstruct_full_chat_history,
    save_view,
)
from aico.historystore import (
    edit_message as edit_message_historystore,
)
from aico.historystore.models import HistoryRecord, SessionView
from aico.historystore.pointer import (
    InvalidPointerError,
    MissingViewError,
)
from aico.historystore.pointer import load_pointer as load_pointer_helper
from aico.lib.models import (
    AssistantChatMessage,
    SessionData,
    UserChatMessage,
)
from aico.lib.session_find import find_session_file


@runtime_checkable
class StatefulSessionPersistence(Protocol):
    def load(self) -> tuple[Path, SessionData]: ...

    def append_pair(self, user_msg: UserChatMessage, asst_msg: AssistantChatMessage) -> None: ...

    def edit_message(
        self,
        message_index: int,
        new_content: str,
        new_metadata: AssistantChatMessage | None = None,
    ) -> None: ...

    def update_view_metadata(
        self,
        *,
        context_files: list[str] | None = None,
        model: str | None = None,
        history_start_pair: int | None = None,
        excluded_pairs: list[int] | None = None,
    ) -> None: ...


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
    _view_path_abs: Path | None
    writable: bool

    def __init__(self, pointer_file: Path):
        self._pointer_file = pointer_file
        self._session_root = pointer_file.parent
        self._history_root = self._session_root / ".aico" / "history"
        self._view_path_abs = None
        self.writable = True

    @property
    def view_path(self) -> Path:
        """Returns the resolved absolute path to the SessionView file."""
        if self._view_path_abs is None:
            # Lazy-load the pointer to resolve the view path
            from aico.historystore.pointer import load_pointer

            self._view_path_abs = load_pointer(self._pointer_file)
        return self._view_path_abs

    # ---------- Load helpers ----------

    def _load_view_and_store(self) -> tuple[HistoryStore, SessionView]:
        """
        Resolve the active SessionView and associated HistoryStore.
        """
        try:
            self._view_path_abs = load_pointer_helper(self._pointer_file)
        except MissingViewError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from e
        except InvalidPointerError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1) from e

        store = HistoryStore(self._history_root)
        try:
            view = load_view(self._view_path_abs)
        except Exception as e:
            typer.echo(
                f"Error: Failed to load session view referenced by pointer ({self._view_path_abs}): {e}",
                err=True,
            )
            raise typer.Exit(1) from e
        return store, view

    # ---------- Load ----------

    def load(self) -> tuple[Path, SessionData]:
        """
        Load the active SessionView and reconstruct a strongly-typed SessionData
        containing only the active window of history.
        """
        store, view = self._load_view_and_store()

        chat_history = reconstruct_chat_history(store, view, include_excluded=True)

        session_data = SessionData(
            model=view.model,
            context_files=list(view.context_files),
            chat_history=chat_history,
            history_start_pair=view.history_start_pair,
            excluded_pairs=list(view.excluded_pairs),
            offset=view.history_start_pair,
        )

        return self._pointer_file, session_data

    def load_full_history(self) -> tuple[Path, SessionData]:
        """
        Load the active SessionView and reconstruct a SessionData containing the full history.
        """
        store, view = self._load_view_and_store()
        chat_history = reconstruct_full_chat_history(store, view)

        session_data = SessionData(
            model=view.model,
            context_files=list(view.context_files),
            chat_history=chat_history,
            history_start_pair=view.history_start_pair,
            excluded_pairs=list(view.excluded_pairs),
            offset=0,
        )

        return self._pointer_file, session_data

    def append_pair(self, user_msg: UserChatMessage, asst_msg: AssistantChatMessage) -> None:
        if not self.writable or self._view_path_abs is None:
            self._fail("Shared-history session is not in a writable state.")
        assert self._view_path_abs is not None

        store = HistoryStore(self._history_root)
        view = load_view(self._view_path_abs)

        user_record = HistoryRecord.from_user_message(user_msg)
        assistant_record = HistoryRecord.from_assistant_message(asst_msg)
        _ = append_pair_to_view(store, view, user_record, assistant_record)

        save_view(self._view_path_abs, view)

    def edit_message(
        self,
        message_index: int,
        new_content: str,
        new_metadata: AssistantChatMessage | None = None,
    ) -> None:
        if not self.writable or self._view_path_abs is None:
            self._fail("Shared-history session is not in a writable state.")
        assert self._view_path_abs is not None

        store = HistoryStore(self._history_root)
        view = load_view(self._view_path_abs)

        if not (0 <= message_index < len(view.message_indices)):
            self._fail("Edited message index out of bounds for current view.")

        # Read the existing record to base the new one on
        original_msg_idx = view.message_indices[message_index]
        old_record = store.read(original_msg_idx)

        # Merge Logic:
        # If new_metadata is provided, it's a full update (e.g. from a recompute/LLM response).
        # If NOT provided, it's a user text edit -> we MUST clear derived fields.
        if new_metadata:
            final_model = new_metadata.model
            final_derived = new_metadata.derived
            final_token_usage = new_metadata.token_usage
            final_cost = new_metadata.cost
            final_duration_ms = new_metadata.duration_ms
        else:
            # Content-only edit invalidates derived data
            final_model = old_record.model
            final_derived = None
            final_token_usage = None
            final_cost = None
            final_duration_ms = old_record.duration_ms

        # Create fully resolved new record
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

        save_view(self._view_path_abs, view)

    def update_view_metadata(
        self,
        *,
        context_files: list[str] | None = None,
        model: str | None = None,
        history_start_pair: int | None = None,
        excluded_pairs: list[int] | None = None,
    ) -> None:
        if not self.writable or self._view_path_abs is None:
            self._fail("Shared-history session is not in a writable state.")
        assert self._view_path_abs is not None

        view = load_view(self._view_path_abs)
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
            save_view(self._view_path_abs, view)

    # ---------- Helpers ----------

    def _fail(self, message: str) -> None:
        raise SessionError(message)


def get_persistence() -> StatefulSessionPersistence:
    """
    Factory for persistence backend; detects pointer file to enable shared-history.
    Fails if a legacy session file is detected.
    """
    session_file_path = find_session_file()
    if session_file_path is None:
        # No session file found. Logic for non-existing sessions must happen upstream (init).
        raise SessionError(f"No session file '{SESSION_FILE_NAME}' found.")

    try:
        raw_text = session_file_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise SessionError(f"Could not read session file {session_file_path}: {e}") from e

    if not raw_text:
        # Treat empty file as invalid/legacy error
        raise SessionIntegrityError(
            f"Session file '{SESSION_FILE_NAME}' is empty. " + "This command requires a shared-history session pointer."
        )

    # Check for legacy format
    if "aico_session_pointer_v1" not in raw_text:
        raise SessionIntegrityError(
            f"Detected a legacy session file at {session_file_path}.\n"
            + "This version of aico only supports the Shared History format.\n"
            + "Please run 'aico migrate-shared-history' to upgrade your project."
        )

    # Use strict loader logic
    try:
        _ = load_pointer_helper(session_file_path)
    except (MissingViewError, InvalidPointerError) as e:
        raise SessionIntegrityError(str(e)) from e

    return SharedHistoryPersistence(session_file_path)
