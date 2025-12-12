from aico.core.session_persistence import SharedHistoryPersistence, get_persistence
from aico.exceptions import InvalidInputError, SessionError
from aico.historystore import HistoryStore, load_view, save_view


def history_splice(
    user_id: int,
    assistant_id: int,
    at_index: int,
) -> None:
    persistence = get_persistence()
    if not isinstance(persistence, SharedHistoryPersistence):
        raise SessionError("This command requires a shared-history session.")

    history_root = persistence.history_root

    store = HistoryStore(history_root)

    # Validate IDs (store.read raises if missing)
    try:
        _ = store.read(user_id)
    except Exception as e:
        raise InvalidInputError(f"User message ID {user_id} not found: {e}") from e

    try:
        _ = store.read(assistant_id)
    except Exception as e:
        raise InvalidInputError(f"Assistant message ID {assistant_id} not found: {e}") from e

    view = load_view(persistence.view_path)

    # Insert at position (pair index * 2)
    target_pos = at_index * 2

    # Allow appending at the very end (target_pos == len)
    if target_pos < 0 or target_pos > len(view.message_indices):
        raise InvalidInputError(
            f"Insertion index {at_index} is out of bounds for history with {len(view.message_indices) // 2} pairs."
        )

    view.message_indices.insert(target_pos, user_id)
    view.message_indices.insert(target_pos + 1, assistant_id)

    save_view(persistence.view_path, view)
    print(f"Splice complete. Inserted pair ({user_id}, {assistant_id}) at index {at_index}.")
