from aico.core.session_loader import load_active_session
from aico.exceptions import InvalidInputError, SessionError
from aico.historystore import switch_active_pointer
from aico.historystore.pointer import load_pointer


def session_switch(
    name: str,
) -> None:
    session = load_active_session()

    # Validate pointer and resolve current active view (ensures shared-history)
    _ = load_pointer(session.file_path)

    sessions_dir = session.root / ".aico" / "sessions"
    if not sessions_dir.is_dir():
        raise SessionError("Sessions directory '.aico/sessions' not found.")

    target_view_path = sessions_dir / f"{name}.json"
    if not target_view_path.is_file():
        raise InvalidInputError(f"Session view '{name}' not found at {target_view_path}.")

    switch_active_pointer(session.file_path, target_view_path)
    print(f"Switched active session to: {name}")
