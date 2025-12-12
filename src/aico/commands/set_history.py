from aico.history_utils import find_message_pairs
from aico.session_context import resolve_start_pair_index
from aico.session_loader import load_active_session


def set_history(
    pair_index_str: str,
) -> None:
    session = load_active_session(full_history=True)

    num_pairs = len(find_message_pairs(session.data.chat_history))

    # Handle the 'clear' keyword before numeric resolution
    if pair_index_str.lower() == "clear":
        pair_index_str = str(num_pairs)

    resolved_index = resolve_start_pair_index(pair_index_str, num_pairs)

    session.persistence.update_view_metadata(history_start_pair=resolved_index)

    # Determine the appropriate success message without re-validating input
    if resolved_index == 0:
        if num_pairs == 0:
            print("History context is empty and active.")
        else:
            print("History context reset. Full chat history is now active.")
    elif resolved_index == num_pairs:
        print("History context cleared (will start after the last conversation).")
    else:
        print(f"History context will now start at pair {resolved_index}.")
