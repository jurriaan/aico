from collections.abc import Sequence

from aico.core.session_loader import load_active_session
from aico.lib.models import ChatMessageHistoryItem
from aico.utils import get_active_history


def format_history_to_markdown(history: Sequence[ChatMessageHistoryItem]) -> str:
    """
    Converts a list of chat messages to a markdown format with role comments.
    """
    log_parts: list[str] = []

    for i, message in enumerate(history):
        # Add a separator between messages, but not before the first one.
        if i > 0:
            log_parts.append("\n\n")

        log_parts.append(f"<!-- llm-role: {message.role} -->\n")
        log_parts.append(message.content)

    return "".join(log_parts)


def dump_history() -> None:
    """
    Export active chat history to stdout in a machine-readable format.
    """
    session = load_active_session()
    active_history = get_active_history(session.data)
    markdown_log = format_history_to_markdown(active_history)
    if markdown_log:
        print(markdown_log, end="")
