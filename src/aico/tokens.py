import sys
from pathlib import Path

import litellm
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from aico.models import SessionData
from aico.utils import SESSION_FILE_NAME, find_session_file

tokens_app = typer.Typer(
    help="Commands for inspecting prompt token usage and costs.",
)


def _load_session() -> tuple[Path, SessionData]:
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. "
            "Please run 'aico init' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    try:
        session_data = SessionData.model_validate_json(session_file.read_text())
    except ValidationError:
        print(
            "Error: Session file is corrupt or has an invalid format.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    return session_file, session_data


@tokens_app.callback(invoke_without_command=True)
def tokens() -> None:
    """
    Calculates and displays the token usage for the current session context.
    """
    session_file, session_data = _load_session()
    session_root = session_file.parent

    console = Console()

    # Base system prompt + diff mode instructions (worst-case scenario for tokens)
    system_prompt = (
        "You are an expert pair programmer."
        "\n\n---\n"
        "IMPORTANT: You are an automated code generation tool. Your response MUST ONLY contain one or more raw SEARCH/REPLACE blocks. "
        "You MUST NOT add any other text, commentary, or markdown. "
        "Your entire response must strictly follow the format specified below.\n"
        "- To create a new file, use an empty SEARCH block.\n"
        "- To delete a file, provide a SEARCH block with the entire file content and an empty REPLACE block.\n\n"
        "EXAMPLE of a multi-file change:\n"
        "File: path/to/existing/file.py\n"
        "<<<<<<< SEARCH\n"
        "    # code to be changed\n"
        "=======\n"
        "    # the new code\n"
        ">>>>>>> REPLACE\n"
        "File: path/to/new/file.py\n"
        "<<<<<<< SEARCH\n"
        "=======\n"
        "def new_function():\n"
        "    pass\n"
        ">>>>>>> REPLACE"
    )

    components = []
    total_tokens = 0

    # 1. System Prompt Tokens
    system_prompt_tokens = litellm.token_counter(
        model=session_data.model, text=system_prompt
    )
    components.append({"description": "system prompt", "tokens": system_prompt_tokens})
    total_tokens += system_prompt_tokens

    # 2. Chat History Tokens
    active_history = session_data.chat_history[session_data.history_start_index :]
    if active_history:
        # Convert Pydantic models to dicts for litellm
        history_messages = [
            {"role": msg.role, "content": msg.content} for msg in active_history
        ]
        history_tokens = litellm.token_counter(
            model=session_data.model, messages=history_messages
        )
        components.append(
            {
                "description": "chat history",
                "tokens": history_tokens,
                "note": "(use 'aico history' to manage)",
            }
        )
        total_tokens += history_tokens

    # 3. Context File Tokens
    for file_path_str in session_data.context_files:
        try:
            file_path = session_root / file_path_str
            content = file_path.read_text()
            # The prompt includes the XML wrapper, so we account for its tokens too
            file_prompt_wrapper = f'<file path="{file_path_str}">\n{content}\n</file>\n'
            file_tokens = litellm.token_counter(
                model=session_data.model, text=file_prompt_wrapper
            )
            components.append(
                {
                    "description": file_path_str,
                    "tokens": file_tokens,
                    "note": "(use 'aico drop' to remove)",
                }
            )
            total_tokens += file_tokens
        except FileNotFoundError:
            # If a file in context is not found, we just ignore it for token counting.
            # The main `prompt` command would show a warning.
            pass

    # Display results
    console.print(
        f"Approximate context window usage for {session_data.model}, in tokens:\n"
    )
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(justify="right")
    table.add_column()
    table.add_column(style="dim")

    for item in components:
        table.add_row(
            f"{item['tokens']:,}",
            item["description"],
            item.get("note", ""),
        )

    # Use a rule for the separator, similar to the reference output
    console.print(table)
    console.print("=" * 22)
    total_table = Table(show_header=False, box=None, padding=(0, 2))
    total_table.add_column(justify="right")
    total_table.add_column()
    total_table.add_row(f"{total_tokens:,}", "tokens total")
    console.print(total_table)
