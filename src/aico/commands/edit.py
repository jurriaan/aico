import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer

from aico.index_logic import load_session_and_resolve_indices
from aico.lib.diffing import recompute_derived_content
from aico.lib.models import AssistantChatMessage
from aico.lib.session import save_session


def edit(
    index: Annotated[
        str,
        typer.Argument(
            help="Index of the message pair to edit (e.g., -1 for last).",
        ),
    ] = "-1",
    prompt: Annotated[
        bool,
        typer.Option(
            "--prompt",
            help="Edit the user prompt instead of the assistant response.",
        ),
    ] = False,
) -> None:
    """
    Open a message in your default editor ($EDITOR) to make corrections.
    """
    session_file, session_data, pair_indices, resolved_pair_index = load_session_and_resolve_indices(index)

    message_type: str
    target_message_index: int
    if prompt:
        message_type = "prompt"
        target_message_index = pair_indices.user_index
    else:
        message_type = "response"
        target_message_index = pair_indices.assistant_index

    target_message = session_data.chat_history[target_message_index]
    original_content = target_message.content

    fd, temp_file_path_str = tempfile.mkstemp(suffix=".txt", text=True)
    temp_file_path = Path(temp_file_path_str)
    try:
        with os.fdopen(fd, "w") as f:
            _ = f.write(original_content)

        editor_cmd_str = os.environ.get("EDITOR", "vi")
        editor_cmd_parts = shlex.split(editor_cmd_str)
        full_command = editor_cmd_parts + [str(temp_file_path)]

        try:
            proc = subprocess.run(full_command, check=False)
        except FileNotFoundError:
            print(
                f"Error: Editor command not found: '{editor_cmd_parts[0]}'. "
                + "Please set the $EDITOR environment variable.",
                file=sys.stderr,
            )
            raise typer.Exit(code=1) from None

        if proc.returncode != 0:
            print("Editor closed with non-zero exit code. Aborting.", file=sys.stderr)
            raise typer.Exit(code=1)

        new_content = temp_file_path.read_text()

        if new_content == original_content:
            print("No changes detected. Aborting.")
            raise typer.Exit(code=0)

        updated_message = replace(target_message, content=new_content)

        # Invalidate derived content if editing an assistant response
        if isinstance(updated_message, AssistantChatMessage):
            session_root = session_file.parent
            new_derived_content = recompute_derived_content(
                assistant_content=new_content,
                context_files=session_data.context_files,
                session_root=session_root,
            )
            updated_message = replace(updated_message, derived=new_derived_content)

        session_data.chat_history[target_message_index] = updated_message
        save_session(session_file, session_data)

        print(f"Updated {message_type} for message pair {resolved_pair_index}.")

    finally:
        temp_file_path.unlink(missing_ok=True)
