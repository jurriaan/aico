from collections.abc import Sequence

from aico.models import ChatMessageHistoryItem
from aico.session_context import build_active_context
from aico.session_loader import load_active_session


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
    session = load_active_session()
    active_history = build_active_context(session.data)["active_history"]
    markdown_log = format_history_to_markdown(active_history)
    if markdown_log:
        print(markdown_log, end="")
