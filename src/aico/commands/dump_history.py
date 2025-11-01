from aico.lib.session import load_session
from aico.utils import format_history_to_markdown, get_active_history


def dump_history() -> None:
    """
    Export active chat history to stdout in a machine-readable format.
    """
    _, session_data = load_session()
    active_history = get_active_history(session_data)
    markdown_log = format_history_to_markdown(active_history)
    if markdown_log:
        print(markdown_log, end="")
