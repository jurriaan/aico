import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import typer

from aico.console import is_input_terminal
from aico.diffing.stream_processor import recompute_derived_content
from aico.exceptions import ExternalDependencyError
from aico.models import AssistantChatMessage
from aico.session_loader import load_session_and_resolve_indices


def edit(
    index: str,
    prompt: bool,
) -> None:
    session, pair_indices, resolved_pair_index = load_session_and_resolve_indices(index)

    message_type: str
    target_message_index: int
    if prompt:
        message_type = "prompt"
        target_message_index = pair_indices.user_index
    else:
        message_type = "response"
        target_message_index = pair_indices.assistant_index

    target_message = session.data.chat_history[target_message_index]
    original_content = target_message.content

    new_content: str

    if not is_input_terminal():
        # Scripted mode: d new content from stdin
        new_content = sys.stdin.read()
    else:
        # Interactive mode: open editor
        fd, temp_file_path_str = tempfile.mkstemp(suffix=".md", text=True)
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
                raise ExternalDependencyError(
                    f"Editor command not found: '{editor_cmd_parts[0]}'. "
                    + "Please set the $EDITOR environment variable."
                ) from None

            if proc.returncode != 0:
                raise ExternalDependencyError("Editor closed with non-zero exit code. Aborting.")

            new_content = temp_file_path.read_text()
        finally:
            temp_file_path.unlink(missing_ok=True)

    if new_content == original_content or not new_content:
        print("No changes detected. Aborting.")
        raise typer.Exit(code=0)

    updated_message = replace(target_message, content=new_content)
    new_asst_metadata: AssistantChatMessage | None = None

    # Invalidate derived content if editing an assistant response
    if isinstance(updated_message, AssistantChatMessage):
        new_derived_content = recompute_derived_content(
            assistant_content=new_content,
            context_files=session.data.context_files,
            session_root=session.root,
        )
        updated_message = replace(updated_message, derived=new_derived_content)
        new_asst_metadata = updated_message

    session.persistence.edit_message(target_message_index, new_content, new_asst_metadata)

    print(f"Updated {message_type} for message pair {resolved_pair_index}.")
