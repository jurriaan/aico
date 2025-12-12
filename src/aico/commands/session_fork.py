import os
import subprocess
import tempfile
from pathlib import Path

import typer

from aico.exceptions import InvalidInputError
from aico.historystore import HistoryStore, find_message_pairs_in_view, fork_view, load_view, switch_active_pointer
from aico.session import Session


def session_fork(
    new_name: str,
    until_pair: int | None,
    ephemeral: bool,
    ctx: typer.Context,
) -> None:
    # Check for execution args
    exec_args = ctx.args

    if not new_name.strip():
        raise InvalidInputError("New session name is required.")

    if ephemeral and not exec_args:
        raise InvalidInputError("--ephemeral is only valid when executing a command via '--'.")

    session = Session.load_active()

    # We use valid properties from our Session object
    active_view_path = session.view_path
    sessions_dir = session.root / ".aico" / "sessions"
    history_root = session.history_root

    if (sessions_dir / f"{new_name}.json").exists():
        raise InvalidInputError(f"A session view named '{new_name}' already exists.")

    store = HistoryStore(history_root)
    view = load_view(active_view_path)

    # Validate until_pair if provided
    if until_pair is not None:
        pairs = find_message_pairs_in_view(store, view)
        if not (0 <= until_pair < len(pairs)):
            raise InvalidInputError(
                f"--until-pair {until_pair} out of range. Valid pair indices: 0 to {len(pairs) - 1}."
            )

    new_view_path = fork_view(store, view, until_pair=until_pair, new_name=new_name, sessions_dir=sessions_dir)

    truncated_str = f" (truncated at pair {until_pair})" if until_pair is not None else ""

    if not exec_args:
        # Standard Fork: Switch active pointer
        switch_active_pointer(session.file_path, new_view_path)
        print(f"Forked new session '{new_name}'{truncated_str} and switched to it.")
    else:
        # Execute in Fork: Use temp pointer, don't switch active session
        fd, temp_ptr_str = tempfile.mkstemp(dir=session.root, suffix=".json", prefix=".aico_ptr_tmp_")
        os.close(fd)
        temp_ptr_path = Path(temp_ptr_str)

        try:
            # Point temp pointer to the new view
            switch_active_pointer(temp_ptr_path, new_view_path)

            env = os.environ.copy()
            env["AICO_SESSION_FILE"] = str(temp_ptr_path.resolve())

            # Run the command with full TTY passthrough
            try:
                # We do not capture output, allowing Rich/Interactive tools to work
                result = subprocess.run(exec_args, env=env, check=False)
                if result.returncode != 0:
                    raise typer.Exit(code=result.returncode)
            except OSError as e:
                typer.echo(f"Error executing command: {e}", err=True)
                raise typer.Exit(code=1) from e

        finally:
            # Cleanup
            temp_ptr_path.unlink(missing_ok=True)
            if ephemeral:
                # If marked ephemeral, clean up the view file too
                new_view_path.unlink(missing_ok=True)
