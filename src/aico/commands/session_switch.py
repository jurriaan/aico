from aico.exceptions import InvalidInputError, SessionError
from aico.historystore import switch_active_pointer
from aico.session import Session


def session_switch(
    name: str,
) -> None:
    session = Session.load_active()

    sessions_dir = session.root / ".aico" / "sessions"
    if not sessions_dir.is_dir():
        raise SessionError("Sessions directory '.aico/sessions' not found.")

    target_view_path = sessions_dir / f"{name}.json"
    if not target_view_path.is_file():
        raise InvalidInputError(f"Session view '{name}' not found at {target_view_path}.")

    switch_active_pointer(session.file_path, target_view_path)
    print(f"Switched active session to: {name}")
