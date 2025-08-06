import contextlib
import sys
from collections.abc import Sequence

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from aico.lib.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    DisplayItem,
    LLMChatMessage,
    SessionData,
    TokenUsage,
    UserChatMessage,
)


def format_tokens(tokens: int) -> str:
    """Formats token counts for display, using 'k' for thousands."""
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


def is_terminal() -> bool:
    """Checks if stdout is a TTY."""
    return sys.stdout.isatty()


def is_input_terminal() -> bool:
    """Checks if stdin is a TTY."""
    return sys.stdin.isatty()


def get_active_history(session_data: SessionData) -> list[ChatMessageHistoryItem]:
    """
    Returns the active slice of chat history based on the start index and excluded messages.
    """
    potential_context_slice = session_data.chat_history[session_data.history_start_index :]
    return [msg for msg in potential_context_slice if not msg.is_excluded]


def reconstruct_historical_messages(
    history: Sequence[ChatMessageHistoryItem],
) -> list[LLMChatMessage]:
    reconstructed: list[LLMChatMessage] = []

    for msg in history:
        reconstructed_msg: LLMChatMessage
        match msg:
            case UserChatMessage(passthrough=True) as m:
                reconstructed_msg = {"role": "user", "content": m.content}
            case UserChatMessage(content=str(prompt), piped_content=str(piped_content)):
                reconstructed_msg = {
                    "role": "user",
                    "content": (
                        f"<stdin_content>\n{piped_content}\n</stdin_content>\n" + f"<prompt>\n{prompt}\n</prompt>"
                    ),
                }
            case UserChatMessage(content=str(prompt)):
                reconstructed_msg = {
                    "role": "user",
                    "content": f"<prompt>\n{msg.content}\n</prompt>",
                }
            case AssistantChatMessage(content=str(content)):
                reconstructed_msg = {"role": "assistant", "content": content}

        reconstructed.append(reconstructed_msg)
    return reconstructed


def render_display_items_to_rich(items: Sequence[DisplayItem]) -> Group:
    """Converts a list of DisplayItems into a Rich Group for rendering."""
    renderables: list[RenderableType] = []
    for item in items:
        if item["type"] == "markdown":
            renderables.append(Markdown(item["content"]))
        elif item["type"] == "diff":
            renderables.append(Syntax(item["content"], "diff"))
        else:
            renderables.append(Text(item["content"], no_wrap=True))
    return Group(*renderables)


def reconstruct_display_content_for_piping(
    display_content: list[DisplayItem] | str | None, mode: str, unified_diff: str | None
) -> str:
    """
    Reconstructs the final string content to print to stdout for non-TTY (piped) output,
    ensuring the contract for each mode is respected.
    """
    # Strict Contract: For 'gen' commands, always print the diff.
    if mode == "diff":
        return unified_diff or ""

    # Flexible Contract: For 'ask' or other modes, prioritize a valid diff,
    # but fall back to the display_content for conversations or errors.
    if unified_diff:
        return unified_diff

    if display_content:
        if isinstance(display_content, list):
            # New format: reconstruct the string from display items
            return "".join(item["content"] for item in display_content)
        # Old format: print the string directly
        return display_content

    return ""


def calculate_and_display_cost(
    token_usage: TokenUsage,
    model_name: str,
    chat_history: Sequence[ChatMessageHistoryItem],
    history_start_index: int,
) -> float | None:
    """Calculates the message cost and displays token/cost information."""
    import litellm

    message_cost: float | None = None
    # Create a mock response object as a dictionary.
    # This provides litellm.completion_cost with the usage data AND the model name
    # in a format it expects for calculating costs robustly.
    mock_response = {
        "usage": {
            "prompt_tokens": token_usage.prompt_tokens,
            "completion_tokens": token_usage.completion_tokens,
            "total_tokens": token_usage.total_tokens,
        },
        "model": model_name,
    }

    with contextlib.suppress(Exception):
        message_cost = litellm.completion_cost(completion_response=mock_response)  # pyright: ignore[reportUnknownMemberType, reportPrivateImportUsage]

    prompt_tokens_str = format_tokens(token_usage.prompt_tokens)
    completion_tokens_str = format_tokens(token_usage.completion_tokens)

    cost_str: str = ""
    if message_cost is not None:
        # "current chat" cost includes all messages from the start index, even excluded ones,
        # because the cost was already incurred.
        current_chat_window = chat_history[history_start_index:]
        window_history_cost = sum(
            msg.cost for msg in current_chat_window if isinstance(msg, AssistantChatMessage) and msg.cost is not None
        )
        # The total cost for the current chat window is the historical cost plus the new message cost
        total_window_cost = window_history_cost + message_cost
        cost_str = f"Cost: ${message_cost:.2f}, current chat: ${total_window_cost:.2f}"

    info_str = f"Tokens: {prompt_tokens_str} sent, {completion_tokens_str} received. {cost_str}"

    if is_terminal():
        console = Console()
        console.print(f"\n[dim]---[/dim]\n[dim]{info_str}[/dim]")
    else:
        print(info_str, file=sys.stderr)

    return message_cost
