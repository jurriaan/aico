from rich.console import Console

from aico.utils import load_session


def status() -> None:
    """
    Shows a summary of the chat history status and active context.
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
