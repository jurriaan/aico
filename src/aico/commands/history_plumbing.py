from aico.exceptions import InvalidInputError
from aico.historystore import HistoryStore, load_view, save_view
from aico.session import Session


def history_splice(
    user_id: int,
    assistant_id: int,
    at_index: int,
) -> None:
    # Use Session.load_active logic to validate and get shared history paths
    # Just loading the session gives us the path and validation
    # Since this is "plumbing", we assume we are operating on the active session
    session = Session.load_active()

    history_root = session.history_root
    store = HistoryStore(history_root)

    # Validate User ID and Assistant ID using read_many
    try:
        records = store.read_many([user_id, assistant_id])
        user_rec, asst_rec = records
        if user_rec.role != "user":
            raise InvalidInputError(f"Message {user_id} is role '{user_rec.role}', expected 'user'.")
        if asst_rec.role != "assistant":
            raise InvalidInputError(f"Message {assistant_id} is role '{asst_rec.role}', expected 'assistant'.")
    except IndexError as e:
        raise InvalidInputError(f"Message ID {user_id} or {assistant_id} not found.") from e
    except ValueError as e:
        raise InvalidInputError(f"History data integrity error: {e}") from e

    view = load_view(session.view_path)

    # Insert at position (pair index * 2)
    target_pos = at_index * 2

    # Allow appending at the very end (target_pos == len)
    if target_pos < 0 or target_pos > len(view.message_indices):
        raise InvalidInputError(
            f"Insertion index {at_index} is out of bounds for history with {len(view.message_indices) // 2} pairs."
        )

    view.message_indices.insert(target_pos, user_id)
    view.message_indices.insert(target_pos + 1, assistant_id)

    save_view(session.view_path, view)
    print(f"Splice complete. Inserted pair ({user_id}, {assistant_id}) at index {at_index}.")
