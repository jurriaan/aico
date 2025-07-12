from rich.console import Console
from rich.table import Table

from aico.index_logic import find_message_pairs
from aico.models import UserChatMessage
from aico.utils import load_session


def log() -> None:
    """
    Display the active conversation log.
    """
    _, session_data = load_session()
    chat_history = session_data.chat_history
    start_index = session_data.history_start_index
    console = Console()

    all_pairs = find_message_pairs(chat_history)
    all_pairs_with_indices = list(enumerate(all_pairs))

    active_pairs_with_indices = [
        (pair_idx, pair) for pair_idx, pair in all_pairs_with_indices if pair.user_index >= start_index
    ]

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
        console.print("No message pairs found in active history.")

    all_paired_indices = {idx for _, pair in all_pairs_with_indices for idx in (pair.user_index, pair.assistant_index)}
    active_dangling_messages = [
        msg for i, msg in enumerate(chat_history) if i not in all_paired_indices and i >= start_index
    ]

    if active_dangling_messages:
        console.print()
        console.print("[yellow]Dangling messages in active context:[/yellow]")
        for msg in active_dangling_messages:
            role = "[blue]user[/blue]" if isinstance(msg, UserChatMessage) else "[green]assistant[/green]"
            lines = msg.content.strip().splitlines()
            snippet = lines[0] if lines else ""
            style = "dim" if msg.is_excluded else ""
            console.print(f"  {role}: {snippet}", style=style)
