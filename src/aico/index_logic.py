import sys
from pathlib import Path

import typer

from aico.lib.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    MessagePairIndices,
    SessionData,
    UserChatMessage,
)
from aico.lib.session import load_session


def find_message_pairs(chat_history: list[ChatMessageHistoryItem]) -> list[MessagePairIndices]:
    """
    Scans the chat history and identifies user/assistant message pairs.

    A pair is defined as a user message followed immediately by an assistant message.

    Args:
        chat_history: The list of chat messages.

    Returns:
        A list of `MessagePairIndices` objects.
    """
    pairs: list[MessagePairIndices] = []
    i = 0
    while i < len(chat_history) - 1:
        current_msg = chat_history[i]
        next_msg = chat_history[i + 1]
        if isinstance(current_msg, UserChatMessage) and isinstance(next_msg, AssistantChatMessage):
            pairs.append(MessagePairIndices(user_index=i, assistant_index=i + 1))
            i += 2  # Move to the next potential pair
        else:
            i += 1
    return pairs


def resolve_pair_index_to_message_indices(
    chat_history: list[ChatMessageHistoryItem], pair_index: int
) -> MessagePairIndices:
    """
    Resolves a human-friendly pair index (positive from start, negative from end)
    to a `MessagePairIndices` object containing the actual list indices.

    Args:
        chat_history: The list of chat messages.
        pair_index: The pair index to resolve (e.g., 0 for the first pair, -1 for the last).

    Returns:
        A `MessagePairIndices` object.

    Raises:
        IndexError: If the pair index is out of bounds with a user-friendly message.
    """
    pairs = find_message_pairs(chat_history)
    num_pairs = len(pairs)

    try:
        return pairs[pair_index]
    except IndexError:
        if not pairs:
            raise IndexError("Error: No message pairs found in history.") from None

        if num_pairs == 1:
            raise IndexError(
                f"Error: Pair at index {pair_index} not found. The only valid index is 0 (or -1)."
            ) from None

        valid_range_str = f"0 to {num_pairs - 1} (or -1 to -{num_pairs})"
        raise IndexError(f"Error: Pair at index {pair_index} not found. Valid indices are {valid_range_str}.") from None


def load_session_and_resolve_indices(
    index_str: str,
) -> tuple[Path, SessionData, MessagePairIndices, int]:
    """
    Loads session, parses index string, and resolves message pair indices.

    Handles all common errors and exits on failure.

    Returns:
        A tuple of (session_file, session_data, pair_indices, resolved_index).
    """
    session_file, session_data = load_session()

    try:
        pair_index_int = int(index_str)
    except ValueError:
        print(f"Error: Invalid index '{index_str}'. Must be an integer.", file=sys.stderr)
        raise typer.Exit(code=1) from None

    try:
        pair_indices = resolve_pair_index_to_message_indices(session_data.chat_history, pair_index_int)
    except IndexError as e:
        print(str(e), file=sys.stderr)
        raise typer.Exit(code=1) from e

    resolved_index = pair_index_int
    if resolved_index < 0:
        # We need to calculate the positive index for user feedback
        # This is safe because resolve_pair_index_to_message_indices has already validated the index
        all_pairs = find_message_pairs(session_data.chat_history)
        resolved_index += len(all_pairs)

    return session_file, session_data, pair_indices, resolved_index
