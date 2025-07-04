import sys
from dataclasses import replace
from typing import Annotated

import typer

from aico.utils import load_session, save_session


def undo(
    count: Annotated[
        int,
        typer.Argument(
            help="Number of conversational pairs (user + assistant) to exclude from context.",
            min=1,
        ),
    ] = 1,
) -> None:
    """
    Mark the last N message pairs as excluded from future context.

    This command performs a "soft delete". The messages are not removed from the
    history, but are flagged to be ignored when building the context for the next
    prompt. This allows you to easily undo recent steps in the conversation without
    losing the record, which is useful if a recent instruction produced an
    undesirable result.
    """
    session_file, session_data = load_session()
    history = session_data.chat_history
    history_len = len(history)
    messages_to_exclude = count * 2

    if history_len == 0:
        print("Error: Cannot undo, chat history is empty.", file=sys.stderr)
        raise typer.Exit(code=1)

    if messages_to_exclude > history_len:
        print(
            f"Error: Cannot undo {count} pairs ({messages_to_exclude} messages), "
            + f"history only contains {history_len} messages.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    excluded_count = 0
    # Iterate backwards through the history to find messages to exclude
    for i in range(history_len - 1, -1, -1):
        if excluded_count >= messages_to_exclude:
            break

        msg = history[i]
        if not msg.is_excluded:
            history[i] = replace(msg, is_excluded=True)
            excluded_count += 1

    if excluded_count == 0:
        print("No active messages found to exclude.", file=sys.stderr)
        raise typer.Exit(code=1)

    save_session(session_file, session_data)
    print(f"Marked the last {excluded_count} messages as excluded.")
