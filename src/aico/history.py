import sys
from typing import Annotated

import typer

from aico.utils import load_session

history_app = typer.Typer(
    name="history",
    help="Commands for managing the chat history context sent to the AI.",
    no_args_is_help=True,
)


@history_app.command()
def view() -> None:
    """
    Shows the current history start index and total message count.
    """
    _, session_data = load_session()
    history_len = len(session_data.chat_history)
    start_index = session_data.history_start_index
    active_messages = history_len - start_index
    print(
        f"Active history starts at index {start_index} of {history_len} total messages."
    )
    print(f"({active_messages} messages will be sent as context in the next prompt.)")


@history_app.command()
def reset() -> None:
    """
    Resets the history start index to 0, making the full history active.
    """
    session_file, session_data = load_session()
    session_data.history_start_index = 0
    _ = session_file.write_text(session_data.model_dump_json(indent=2))
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
        print(
            f"Error: Invalid index '{index_str}'. Must be an integer.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    # An index of history_len is valid; it means sending no history.
    if not (0 <= target_index <= history_len):
        print(
            f"Error: Index out of bounds. Must be between 0 and {history_len} (inclusive), but got {target_index}.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    session_data.history_start_index = target_index
    _ = session_file.write_text(session_data.model_dump_json(indent=2))
    print(f"History start index set to {target_index}.")
