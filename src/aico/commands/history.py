import sys
from typing import Annotated

import typer

from aico.utils import load_session, save_session

history_app = typer.Typer(
    name="history",
    help="Commands for managing the chat history context sent to the AI.",
    no_args_is_help=True,
)


@history_app.command()
def view() -> None:
    """
    Shows a summary of the chat history status.
    """
    _, session_data = load_session()
    history = session_data.chat_history
    history_len = len(history)

    if history_len == 0:
        print("Chat history is empty.")
        return

    start_index = session_data.history_start_index
    total_excluded_count = sum(1 for msg in history if msg.is_excluded)

    potential_context_slice = history[start_index:]
    truly_active_count = sum(1 for msg in potential_context_slice if not msg.is_excluded)

    main_status_parts = [
        f"History contains {history_len} total messages.",
        f"The next prompt will use {truly_active_count} of these, starting from message {start_index}.",
    ]
    if total_excluded_count > 0:
        main_status_parts.append(
            f"{total_excluded_count} messages are excluded in total (use 'aico undo' to exclude more)."
        )

    print(" ".join(main_status_parts))


@history_app.command()
def reset() -> None:
    """
    Resets the history start index to 0, making the full history active.
    """
    session_file, session_data = load_session()
    session_data.history_start_index = 0
    save_session(session_file, session_data)
    print("History index reset to 0. Full chat history is now active.")


@history_app.command(name="set", context_settings={"ignore_unknown_options": True})
def set_index(
    index_str: Annotated[
        str,
        typer.Argument(
            ...,
            help="The new start index. Can be an absolute number (e.g., '10') or relative from the end (e.g., '-5').",
        ),
    ],
) -> None:
    """
    Sets the history start index to control how much context is sent.
    """
    session_file, session_data = load_session()
    history_len = len(session_data.chat_history)
    target_index: int

    try:
        if index_str.startswith("-"):
            offset = int(index_str)
            target_index = history_len + offset
        else:
            target_index = int(index_str)
    except ValueError:
        print(f"Error: Invalid index '{index_str}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    # An index of history_len is valid; it means sending no history.
    if not (0 <= target_index <= history_len):
        print(
            f"Error: Index out of bounds. Must be between 0 and {history_len} (inclusive), but got {target_index}.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    session_data.history_start_index = target_index
    save_session(session_file, session_data)
    print(f"History start index set to {target_index}.")
