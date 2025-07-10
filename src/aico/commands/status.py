from rich.console import Console

from aico.index_logic import find_message_pairs
from aico.utils import load_session


def status() -> None:
    """
    Shows a summary of the chat history status and active context.
    """
    _, session_data = load_session()
    history = session_data.chat_history

    console = Console()

    if not history:
        console.print("Chat history is empty.")
        return

    all_pairs_with_indices = list(enumerate(find_message_pairs(history)))
    total_pairs = len(all_pairs_with_indices)

    total_excluded_pairs = sum(1 for _, pair in all_pairs_with_indices if history[pair.user_index].is_excluded)

    console.print("[bold]Full History Summary:[/bold]")
    console.print(f"  Total message pairs: {total_pairs}")
    if total_excluded_pairs > 0:
        console.print(f"  Total excluded pairs: {total_excluded_pairs}")

    console.print()

    # Current context
    start_index = session_data.history_start_index
    active_pairs_with_indices = [
        (pair_idx, pair) for pair_idx, pair in all_pairs_with_indices if pair.user_index >= start_index
    ]

    console.print("[bold]Current Context (for next prompt):[/bold]")

    if not active_pairs_with_indices:
        # Check for non-paired messages that might still be sent.
        potential_context_slice = history[start_index:]
        sent_messages = [msg for msg in potential_context_slice if not msg.is_excluded]

        if sent_messages:
            console.print(f"  Context to be sent: {len(sent_messages)} partial or dangling messages")
        else:
            console.print("  No active context to be sent.")
        return

    active_window_pairs = len(active_pairs_with_indices)
    active_start_id = active_pairs_with_indices[0][0]
    active_end_id = active_pairs_with_indices[-1][0]
    plural_s = "s" if active_window_pairs != 1 else ""
    window_id_str = (
        f"ID {active_start_id}" if active_start_id == active_end_id else f"IDs {active_start_id}-{active_end_id}"
    )

    console.print(f"  Active window: {window_id_str} ({active_window_pairs} pair{plural_s})")

    excluded_in_window = sum(1 for _, pair in active_pairs_with_indices if history[pair.user_index].is_excluded)
    pairs_to_be_sent = active_window_pairs - excluded_in_window
    excluded_str = f" ({excluded_in_window} are excluded via `aico undo`)" if excluded_in_window else ""

    console.print(f"  Context to be sent: {pairs_to_be_sent} of {active_window_pairs} active pairs{excluded_str}")
