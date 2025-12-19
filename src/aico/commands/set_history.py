from aico.session import Session, resolve_start_pair_index


def set_history(
    pair_index_str: str,
) -> None:
    session = Session.load_active()

    num_pairs = session.num_pairs

    # Handle the 'clear' keyword before numeric resolution
    if pair_index_str.lower() == "clear":
        pair_index_str = str(num_pairs)

    resolved_index = resolve_start_pair_index(pair_index_str, num_pairs)

    session.update_view_metadata(history_start_pair=resolved_index)

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
