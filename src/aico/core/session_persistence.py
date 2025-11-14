import copy
import sys
from dataclasses import replace
from json import JSONDecodeError
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
    load_view,
    reconstruct_chat_history,
    save_view,
)
from aico.historystore import (
    edit_message as edit_message_historystore,
)
from aico.historystore.models import HistoryRecord, UserMetaEnvelope
from aico.historystore.pointer import (
    InvalidPointerError,
    MissingViewError,
    SessionPointer,
)
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
    SESSION_FILE_NAME,
    SessionDataAdapter,
    find_session_file,
)
from aico.lib.session import (
    save_session as legacy_save_session,
)


@runtime_checkable
class SessionPersistence(Protocol):
    def load(self) -> tuple[Path, SessionData]: ...
    def save(self, session_file: Path, session_data: SessionData) -> None: ...


@runtime_checkable
class StatefulSessionPersistence(SessionPersistence, Protocol):
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


class LegacyJsonPersistence:
    """
    Manages session state for the legacy single-file JSON format.

    This class is stateless. Each write operation performs a full load-mutate-save cycle.
    """

    def load(self) -> tuple[Path, SessionData]:
        session_file = find_session_file()
        if not session_file:
            print(f"Error: No session file '{SESSION_FILE_NAME}' found. Please run 'aico init' first.", file=sys.stderr)
            raise typer.Exit(code=1)

        try:
            session_data = SessionDataAdapter.validate_json(session_file.read_text())
        except (ValidationError, JSONDecodeError) as e:
            print("Error: Session file is corrupt or has an invalid format", file=sys.stderr)
            print(e, file=sys.stderr)
            raise typer.Exit(code=1) from e
        except Exception as e:
            print(f"Error: Could not load session file {session_file}: {e}", file=sys.stderr)
            raise typer.Exit(code=1) from e

        chat_history = session_data.chat_history

        # One-way, in-memory upgrade for backward compatibility.
        # This derives canonical fields from legacy fields if they are present.

        # 1. Derive `excluded_pairs` from legacy `is_excluded` flags if `excluded_pairs` is empty.
        has_legacy_exclusions = any(msg.is_excluded for msg in chat_history)
        if not session_data.excluded_pairs and has_legacy_exclusions:
            pairs = find_message_pairs(chat_history)
            session_data.excluded_pairs = [
                idx
                for idx, p in enumerate(pairs)
                if chat_history[p.user_index].is_excluded and chat_history[p.assistant_index].is_excluded
            ]

        # 2. Derive `history_start_pair` from legacy `history_start_index`.
        if (
            session_data.history_start_pair == 0
            and session_data.history_start_index is not None
            and session_data.history_start_index > 0
        ):
            session_data.history_start_pair = map_history_start_index_to_pair(
                chat_history, session_data.history_start_index
            )

        return session_file, session_data

    def save(self, session_file: Path, session_data: SessionData) -> None:
        """Saves session data. Used by `init`."""
        legacy_save_session(session_file, session_data)

    def append_pair(self, user_msg: UserChatMessage, asst_msg: AssistantChatMessage) -> None:
        session_file, session_data = self.load()
        session_data.chat_history.append(user_msg)
        session_data.chat_history.append(asst_msg)
        legacy_save_session(session_file, session_data)

    def edit_message(
        self,
        message_index: int,
        new_content: str,
        new_metadata: AssistantChatMessage | None = None,
    ) -> None:
        session_file, session_data = self.load()

        if new_metadata:
            session_data.chat_history[message_index] = new_metadata
        else:
            target_message = session_data.chat_history[message_index]
            updated_message = replace(target_message, content=new_content)
            session_data.chat_history[message_index] = updated_message

        legacy_save_session(session_file, session_data)

    def update_view_metadata(
        self,
        *,
        context_files: list[str] | None = None,
        model: str | None = None,
        history_start_pair: int | None = None,
        excluded_pairs: list[int] | None = None,
    ) -> None:
        session_file, session_data = self.load()

        changed = False
        if context_files is not None:
            sorted_files = sorted(context_files)
            if session_data.context_files != sorted_files:
                session_data.context_files = sorted_files
                changed = True
        if model is not None and session_data.model != model:
            session_data.model = model
            changed = True
        if history_start_pair is not None and session_data.history_start_pair != history_start_pair:
            session_data.history_start_pair = history_start_pair
            changed = True
        if excluded_pairs is not None:
            sorted_excluded = sorted(excluded_pairs)
            if sorted(session_data.excluded_pairs) != sorted_excluded:
                session_data.excluded_pairs = sorted_excluded
                changed = True

        if changed:
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

        chat_history = reconstruct_chat_history(store, view)

        session_data = SessionData(
            model=view.model,
            context_files=list(view.context_files),
            chat_history=chat_history,
            history_start_pair=view.history_start_pair,
            excluded_pairs=list(view.excluded_pairs),
        )

        # Snapshot for diffing on save
        self._original_session = copy.deepcopy(session_data)
        return self._pointer_file, session_data

    def append_pair(self, user_msg: UserChatMessage, asst_msg: AssistantChatMessage) -> None:
        if not self.writable or self._view_path_abs is None:
            self._fail("Shared-history session is not in a writable state.")
        assert self._view_path_abs is not None

        store = HistoryStore(self._history_root)
        view = load_view(self._view_path_abs)

        user_record = self._to_history_record_user(user_msg)
        assistant_record = self._to_history_record_assistant(asst_msg)
        _ = append_pair_to_view(store, view, user_record, assistant_record)

        save_view(self._view_path_abs, view)

        # Update internal state to prevent old save method from tripping on length changes
        if self._original_session:
            self._original_session.chat_history.append(user_msg)
            self._original_session.chat_history.append(asst_msg)

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

        if new_metadata:
            _ = edit_message_historystore(
                store,
                view,
                message_index,
                new_content,
                model=new_metadata.model,
                derived=new_metadata.derived,
                token_usage=new_metadata.token_usage,
                cost=new_metadata.cost,
                duration_ms=new_metadata.duration_ms,
            )
        else:
            _ = edit_message_historystore(store, view, message_index, new_content)

        save_view(self._view_path_abs, view)

        if self._original_session:
            original_message = self._original_session.chat_history[message_index]
            updated_message = replace(original_message, content=new_content)
            if new_metadata and isinstance(updated_message, AssistantChatMessage):
                updated_message = replace(
                    updated_message,
                    model=new_metadata.model,
                    derived=new_metadata.derived,
                    token_usage=new_metadata.token_usage,
                    cost=new_metadata.cost,
                    duration_ms=new_metadata.duration_ms,
                )
            self._original_session.chat_history[message_index] = updated_message

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
        if excluded_pairs is not None and sorted(set(view.excluded_pairs)) != sorted(set(excluded_pairs)):
            view.excluded_pairs = sorted(set(excluded_pairs))
            changed = True

        if changed:
            save_view(self._view_path_abs, view)

    # ---------- Save (Legacy entrypoint for metadata changes) ----------

    def save(self, session_file: Path, session_data: SessionData) -> None:
        del session_file
        if not self.writable:
            typer.echo(
                "Error: This is a read-only shared-history session. Write commands are not supported.",
                err=True,
            )
            raise typer.Exit(code=1)

        if self._original_session is None:
            typer.echo("Error: Internal state missing for shared-history save (no session loaded).", err=True)
            raise typer.Exit(code=1)

        original = self._original_session
        new = session_data

        # This save method is now only for metadata-only changes.
        # Appends and Edits must be handled by proactive methods.
        if len(original.chat_history) != len(new.chat_history):
            self._fail(
                "Unhandled history length modification detected in save(). "
                + f"Original: {len(original.chat_history)}, New: {len(new.chat_history)}. "
                + "Use append_pair() or edit_message()."
            )

        content_diffs = [
            i
            for i, (o_msg, n_msg) in enumerate(zip(original.chat_history, new.chat_history, strict=True))
            if o_msg.content != n_msg.content
        ]
        if content_diffs:
            self._fail(
                f"Unhandled content modification detected in save() for indices {content_diffs}. Use edit_message()."
            )

        # If we get here, it's a metadata-only change.
        self.update_view_metadata(
            context_files=new.context_files,
            model=new.model,
            history_start_pair=new.history_start_pair,
            excluded_pairs=new.excluded_pairs,
        )

        # Update snapshot for subsequent saves within the same process
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


def get_persistence(require_type: str = "any") -> StatefulSessionPersistence:
    """
    Factory for persistence backend; detects pointer file to enable shared-history.

    Args:
        require_type: Controls which persistence types are acceptable.
            - "any": return either LegacyJsonPersistence or SharedHistoryPersistence.
            - "shared": require a valid shared-history session (pointer + view); otherwise exit.
    """
    session_file_path = find_session_file()
    if session_file_path is None:
        if require_type == "shared":
            print(
                f"Error: No session file '{SESSION_FILE_NAME}' found. "
                + "This command requires a shared-history session. "
                + "Run 'aico init' or 'aico migrate-shared-history' first.",
                file=sys.stderr,
            )
            raise typer.Exit(code=1)
        return LegacyJsonPersistence()

    try:
        raw_text = session_file_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        if require_type == "shared":
            print(f"Error: Could not read session file {session_file_path}: {e}", file=sys.stderr)
            raise typer.Exit(code=1) from e
        return LegacyJsonPersistence()

    if not raw_text:
        if require_type == "shared":
            print(
                f"Error: Session file '{SESSION_FILE_NAME}' is empty. "
                + "This command requires a shared-history session pointer.",
                file=sys.stderr,
            )
            raise typer.Exit(code=1)
        return LegacyJsonPersistence()

    # Optimization: if it doesn't contain the magic string, it can't be a pointer.
    if "aico_session_pointer_v1" not in raw_text:
        if require_type == "shared":
            print(
                "Error: This command requires a shared-history session. "
                + "Run 'aico migrate-shared-history' to upgrade this legacy session.",
                file=sys.stderr,
            )
            raise typer.Exit(code=1)
        return LegacyJsonPersistence()

    # It looks like a pointer.
    if require_type == "shared":
        # If shared is required, be strict: load_pointer must succeed completely.
        try:
            _ = load_pointer_helper(session_file_path)
        except MissingViewError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=1) from e
        except InvalidPointerError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1) from e
    else:
        # If any type is allowed, be lenient.
        # It's a pointer if it can be parsed as one, even if the view is missing.
        try:
            _ = SessionPointer.model_validate_json(raw_text)
        except ValidationError:
            return LegacyJsonPersistence()

    return SharedHistoryPersistence(session_file_path)
