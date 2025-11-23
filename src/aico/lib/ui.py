"""UI rendering, display, and terminal utilities."""

import sys
from collections.abc import Sequence
from typing import Literal

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from aico.core.session_context import get_start_message_index
from aico.core.tokens import compute_component_cost
from aico.lib.model_info import get_model_info
from aico.lib.models import (
    AssistantChatMessage,
    DisplayItem,
    Mode,
    SessionData,
    TokenUsage,
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
    display_content: list[DisplayItem] | str | None,
    mode: Mode | Literal["diff", "conversation", "raw"],
    unified_diff: str | None,
) -> str:
    """
    Reconstructs the final string content to print to stdout for non-TTY (piped) output,
    ensuring the contract for each mode is respected.
    """
    mode_value: str = mode.value if isinstance(mode, Mode) else str(mode)

    # Strict contract for 'gen' (diff) mode: only print the unified diff; otherwise empty.
    if mode_value == "diff":
        return unified_diff or ""

    # Flexible contract for other modes: prefer a valid diff, else fall back to display content.
    if unified_diff:
        return unified_diff

    if display_content:
        if isinstance(display_content, list):
            return "".join(item["content"] for item in display_content)
        return display_content

    return ""


def calculate_and_display_cost(
    token_usage: TokenUsage,
    model_name: str,
    session_data: SessionData,
    exact_cost: float | None = None,
) -> float | None:
    """Calculates the message cost and displays token/cost information."""
    model = get_model_info(model_name)

    # Prefer usage.cost (OpenRouter injection) or exact_cost passed in
    message_cost = token_usage.cost if token_usage.cost is not None else exact_cost
    if message_cost is None:
        # Fallback to estimating cost if available (stub for now until cleanup)
        message_cost = compute_component_cost(model, token_usage.prompt_tokens, token_usage.completion_tokens)

    prompt_tokens_str = format_tokens(token_usage.prompt_tokens)
    if token_usage.cached_tokens:
        prompt_tokens_str += f" ({format_tokens(token_usage.cached_tokens)} cached)"

    completion_tokens_str = format_tokens(token_usage.completion_tokens)
    if token_usage.reasoning_tokens:
        completion_tokens_str += f" ({format_tokens(token_usage.reasoning_tokens)} reasoning)"

    cost_str: str = ""
    if message_cost is not None:
        # "current chat" cost includes all messages from the start index, even excluded ones,
        # because the cost was already incurred.
        start_message_idx = get_start_message_index(session_data)
        current_chat_window = session_data.chat_history[start_message_idx:]
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
