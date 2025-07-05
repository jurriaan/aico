import sys
from typing import Annotated

import typer

from aico.utils import load_session, save_session

history_app = typer.Typer(
    name="history",
    help="Commands for managing the chat history context sent to the AI.",
    no_args_is_help=True,
)


from rich.console import Console


@history_app.command()
def view() -> None:
    """
    Shows a summary of the chat history status.
    """
    _, session_data = load_session()
    history = session_data.chat_history
    history_len = len(history)

    console = Console()

    if history_len == 0:
        console.print("Chat history is empty.")
        return

    # Full history summary
    total_excluded_count = sum(1 for msg in history if msg.is_excluded)
    console.print("[bold]Full history summary:[/bold]")
    console.print(f"Total messages: {history_len} recorded.")
    console.print(f"Total excluded: {total_excluded_count} (across the entire history).")

    console.print()

    # Current context
    start_index = session_data.history_start_index
    potential_context_slice = history[start_index:]
    active_window_size = len(potential_context_slice)
    excluded_in_window = sum(1 for msg in potential_context_slice if msg.is_excluded)
    messages_to_be_sent = active_window_size - excluded_in_window

    console.print("[bold]Current context (for next prompt):[/bold]")
    console.print(f"Messages to be sent: {messages_to_be_sent}")

    indices_str_part = ""
    if active_window_size > 0:
        end_index = history_len - 1
        if start_index == end_index:
            indices_str_part = f" (index {start_index})"
        else:
            indices_str_part = f" (indices {start_index}-{end_index})"

    console.print(
        f"    [italic](From an active window of {active_window_size} messages{indices_str_part}, "
        f"with {excluded_in_window} excluded via `aico undo`)[/italic]"
    )


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
