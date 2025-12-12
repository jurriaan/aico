from pathlib import Path

from aico.consts import SESSION_FILE_NAME
from aico.historystore import (
    HistoryStore,
    SessionView,
    append_pair_to_view,
    save_view,
    switch_active_pointer,
)
from aico.historystore.models import HistoryRecord
from aico.models import AssistantChatMessage, SessionData, UserChatMessage


def save_session(path: Path, data: SessionData) -> None:
    """Test helper to save a session in the legacy JSON format."""
    # Use TypeAdapter because SessionData is a dataclass, not a BaseModel
    init_shared_session(path.parent, data)


def load_session_data(session_file: Path) -> SessionData:
    from aico.models import SessionData
    from aico.session import Session

    # Instantiate directly to bypass session discovery env vars
    session = Session(session_file, SessionData(model="placeholder"))
    # Load without full history to match default behavior of load()
    session._load(full_history=False)  # pyright: ignore[reportPrivateUsage]
    return session.data


def init_shared_session(project_root: Path, data: SessionData, view_name: str = "main") -> None:
    """
    Test helper to initialize a valid Shared History session structure from SessionData.
    Creates:
      - .aico/history/
      - .aico/sessions/<view_name>.json
      - .ai_session.json (pointer)
    """
    history_root = project_root / ".aico" / "history"
    sessions_dir = project_root / ".aico" / "sessions"
    history_root.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    store = HistoryStore(history_root)

    # Initialize View
    view = SessionView(
        model=data.model,
        context_files=list(data.context_files),
        message_indices=[],
        history_start_pair=data.history_start_pair,
        excluded_pairs=list(data.excluded_pairs),
    )

    # Convert flat list of messages into pairs and append to store/view
    # We assume the test data is well-formed (User -> Assistant -> User ...)
    for i in range(0, len(data.chat_history), 2):
        if i + 1 >= len(data.chat_history):
            # Handle dangling user message
            u_msg = data.chat_history[i]
            assert isinstance(u_msg, UserChatMessage), f"{i} is not UserChatMessage, but {u_msg}"
            # Create a dummy assistant record to satisfy append_pair requirements for now,
            # or handle dangling insertion if your API supports it.
            # Note: append_pair_to_view requires a pair.
            # If your tests use dangling messages, we might need a lower-level append.

            # Low-level append for dangling:
            rec = HistoryRecord(
                role="user",
                content=u_msg.content,
                mode=u_msg.mode,
                timestamp=u_msg.timestamp,
                passthrough=u_msg.passthrough,
                piped_content=u_msg.piped_content,
            )
            idx = store.append(rec)
            view.message_indices.append(idx)
            break

        u_msg = data.chat_history[i]
        assert isinstance(u_msg, UserChatMessage), f"{i} is not UserChatMessage, but {u_msg}"
        a_msg = data.chat_history[i + 1]
        assert isinstance(a_msg, AssistantChatMessage), f"{i} is not UserChatMessage, but {u_msg}"

        u_rec = HistoryRecord(
            role="user",
            content=u_msg.content,
            mode=u_msg.mode,
            timestamp=u_msg.timestamp,
            passthrough=u_msg.passthrough,
            piped_content=u_msg.piped_content,
        )

        # Handle derived content types safely
        derived = None
        if hasattr(a_msg, "derived"):
            derived = a_msg.derived

        a_rec = HistoryRecord(
            role="assistant",
            content=a_msg.content,
            mode=a_msg.mode,
            timestamp=a_msg.timestamp,
            model=getattr(a_msg, "model", data.model),
            duration_ms=getattr(a_msg, "duration_ms", 0),
            cost=getattr(a_msg, "cost", None),
            token_usage=getattr(a_msg, "token_usage", None),
            derived=derived,
        )

        _ = append_pair_to_view(store, view, u_rec, a_rec)

    # Save View
    view_path = sessions_dir / f"{view_name}.json"
    save_view(view_path, view)

    # Create Pointer
    session_file = project_root / SESSION_FILE_NAME
    switch_active_pointer(session_file, view_path)
