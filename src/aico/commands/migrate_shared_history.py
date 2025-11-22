import json
import sys

import typer
from pydantic import TypeAdapter, ValidationError

from aico.historystore import from_legacy_session, switch_active_pointer
from aico.historystore.pointer import SessionPointer
from aico.lib.session import SESSION_FILE_NAME, SessionDataAdapter, find_session_file


def migrate_shared_history(
    name: str,
    backup: bool,
    force: bool,
) -> None:
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found in this directory or its parents.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    try:
        raw_text = session_file.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error: Could not read session file {session_file}: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from e

    # Already a pointer?
    try:
        _ = TypeAdapter(SessionPointer).validate_json(raw_text)
        print("This session is already using the shared-history format. Nothing to migrate.")
        raise typer.Exit(code=0)
    except ValidationError:
        # Not a pointer, which is what we expect. Continue to parse as legacy.
        pass

    try:
        session_data = SessionDataAdapter.validate_json(raw_text)
    except (ValidationError, json.JSONDecodeError) as e:
        print(f"Error: Failed to parse session file as a valid legacy session {session_file}: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from e

    # Prepare paths
    session_root = session_file.parent
    history_root = session_root / ".aico" / "history"
    sessions_dir = session_root / ".aico" / "sessions"
    view_path = sessions_dir / f"{name}.json"

    if view_path.exists() and not force:
        print(
            f"Error: Target view already exists: {view_path}\nUse --force to overwrite or choose a different --name.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    # Backup legacy file if requested
    if backup:
        backup_path = session_root / ".ai_session.legacy.json"
        if backup_path.exists():
            print(
                f"Warning: Backup file already exists, skipping backup: {backup_path}",
                file=sys.stderr,
            )
        else:
            try:
                _ = backup_path.write_text(raw_text, encoding="utf-8")
                print(f"Legacy session backed up to: {backup_path}")
            except Exception as e:
                print(f"Warning: Failed to write backup file: {e}", file=sys.stderr)

    # Perform migration
    try:
        _ = from_legacy_session(
            session_data=session_data,
            history_root=history_root,
            sessions_dir=sessions_dir,
            name=name,
        )
    except Exception as e:
        print(f"Error: Migration failed: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from e

    # Switch pointer
    try:
        switch_active_pointer(session_file, view_path)
    except Exception as e:
        print(f"Error: Failed to update session pointer: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from e

    print(
        "Migrated legacy session to shared-history:\n"
        + f"- View: {view_path}\n"
        + f"- History root: {history_root}\n"
        + f"- Pointer updated: {session_file}"
    )
