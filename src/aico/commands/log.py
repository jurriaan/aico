from rich.console import Console
from rich.table import Table

from aico.core.session_context import active_message_indices, get_active_message_pairs
from aico.core.session_loader import load_active_session
from aico.lib.history_utils import find_message_pairs
from aico.lib.models import UserChatMessage


def log() -> None:
    session = load_active_session()
    chat_history = session.data.chat_history
    console = Console()

    # Use centralized helper to get pairs in the active window with their absolute indices
    active_pairs_with_indices = get_active_message_pairs(session.data)

    # Determine active indices using centralized helper
    active_indices_set = set(active_message_indices(session.data, include_dangling=True))

    if active_pairs_with_indices:
        table = Table(title="Active Context Log", show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("ID", justify="right")
        table.add_column("Role")
        table.add_column("Message Snippet", overflow="ellipsis", min_width=20)

        excluded_set = set(session.data.excluded_pairs)

        for i, (pair_index, pair) in enumerate(active_pairs_with_indices):
            user_msg = chat_history[pair.user_index]
            asst_msg = chat_history[pair.assistant_index]

            pair_excluded = pair_index in excluded_set
            user_row_style = "dim" if pair_excluded else ""
            asst_row_style = "dim" if pair_excluded else ""

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
        console.print("No message pairs found in active history.")

    # For dangling messages, we need to know which messages in the current history list are part of any pair.
    # This is safe for both legacy (full history) and shared (sliced history) sessions.
    all_pairs_in_current_history = find_message_pairs(chat_history)
    all_paired_indices = {
        idx for pair in all_pairs_in_current_history for idx in (pair.user_index, pair.assistant_index)
    }

    # Dangling messages are active if in active_indices_set and not part of a pair
    active_dangling_messages = [
        msg for i, msg in enumerate(chat_history) if i not in all_paired_indices and i in active_indices_set
    ]

    if active_dangling_messages:
        console.print()
        console.print("[yellow]Dangling messages in active context:[/yellow]")
        for msg in active_dangling_messages:
            role = "[blue]user[/blue]" if isinstance(msg, UserChatMessage) else "[green]assistant[/green]"
            lines = msg.content.strip().splitlines()
            snippet = lines[0] if lines else ""
            console.print(f"  {role}: {snippet}")
