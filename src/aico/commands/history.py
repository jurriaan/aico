import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from aico.index_logic import find_message_pairs
from aico.models import UserChatMessage
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
        + f"with {excluded_in_window} excluded via `aico undo`)[/italic]"
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


@history_app.command()
def log() -> None:
    """
    Shows a compact log of the active chat history context.
    """
    _, session_data = load_session()
    chat_history = session_data.chat_history
    start_index = session_data.history_start_index
    console = Console()

    all_pairs = find_message_pairs(chat_history)
    active_pairs_with_indices = [(i, pair) for i, pair in enumerate(all_pairs) if pair.user_index >= start_index]

    if active_pairs_with_indices:
        table = Table(title="Active Context Log", show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("ID", justify="right")
        table.add_column("Role")
        table.add_column("Message Snippet", overflow="ellipsis", min_width=20)

        for i, (pair_index, pair) in enumerate(active_pairs_with_indices):
            user_msg = chat_history[pair.user_index]
            asst_msg = chat_history[pair.assistant_index]

            user_row_style = "dim" if user_msg.is_excluded else ""
            asst_row_style = "dim" if asst_msg.is_excluded else ""

            user_lines = user_msg.content.strip().splitlines()
            user_snippet = user_lines[0] if user_lines else ""

            asst_lines = asst_msg.content.strip().splitlines()
            asst_snippet = asst_lines[0] if asst_lines else ""

            table.add_row(
                str(pair_index),
                "[blue]user[/blue]",
                user_snippet,
                style=user_row_style,
            )

            table.add_row(
                "",
                "[green]assistant[/green]",
                asst_snippet,
                style=asst_row_style,
                end_section=(i < len(active_pairs_with_indices) - 1),
            )
        console.print(table)
    else:
        console.print("No message pairs found in active context.")

    active_paired_indices = {
        idx for _, pair in active_pairs_with_indices for idx in (pair.user_index, pair.assistant_index)
    }
    dangling_messages = [
        msg for i, msg in enumerate(chat_history) if i >= start_index and i not in active_paired_indices
    ]

    if dangling_messages:
        console.print()
        console.print("[yellow]Dangling messages in active context (not part of a pair):[/yellow]")
        for msg in dangling_messages:
            role = "[blue]user[/blue]" if isinstance(msg, UserChatMessage) else "[green]assistant[/green]"
            lines = msg.content.strip().splitlines()
            snippet = lines[0] if lines else ""
            style = "dim" if msg.is_excluded else ""
            console.print(f"  {role}: {snippet}", style=style)


@history_app.command(name="set", context_settings={"ignore_unknown_options": True})
def set_index(
    pair_index_str: Annotated[
        str,
        typer.Argument(
            ...,
            help="The pair index to set as the start of the active context. "
            + "Use negative numbers to count from the end, or the total number of pairs to clear context.",
        ),
    ],
) -> None:
    """
    Sets the history start point to the beginning of a specific message pair.

    Use `aico history log` to see available pair indices. You can also specify
    an index equal to the total number of pairs to set the start point after
    all conversations, effectively clearing the active context for the next prompt.
    """
    session_file, session_data = load_session()
    chat_history = session_data.chat_history

    try:
        pair_index_val = int(pair_index_str)
    except ValueError:
        print(f"Error: Invalid index '{pair_index_str}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    pairs = find_message_pairs(chat_history)
    num_pairs = len(pairs)
    target_message_index: int

    if -num_pairs <= pair_index_val < num_pairs:
        # Valid positive or negative index for an existing pair
        target_message_index = pairs[pair_index_val].user_index
    elif pair_index_val == num_pairs:
        # Special case: set start index after the last pair, clearing the context
        target_message_index = len(chat_history)
    else:
        # Index is out of bounds
        if num_pairs == 0:
            err_msg = "Error: No message pairs found. Cannot set history index."
        elif num_pairs == 1:
            err_msg = "Error: Index out of bounds. Valid index is 0 (or -1), or 1 to clear context."
        else:
            valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
            err_msg = f"Error: Index out of bounds. Valid indices are in the range {valid_range_str}, "
            err_msg += f"or {num_pairs} to clear context."
        print(err_msg, file=sys.stderr)
        raise typer.Exit(code=1)

    session_data.history_start_index = target_message_index
    save_session(session_file, session_data)

    if pair_index_val == num_pairs:
        print("History context cleared (will start after the last pair).")
    else:
        print(f"History context will now start at pair {pair_index_str}.")
