"""UI rendering, display, and terminal utilities."""

import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from rich.console import Group

from aico.models import (
    AssistantChatMessage,
    DisplayItem,
    Mode,
    SessionData,
    TokenUsage,
)
from aico.session import get_active_message_pairs


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


def render_display_items_to_rich(items: Sequence[DisplayItem]) -> "Group":
    """Converts a list of DisplayItems into a Rich Group for rendering."""
    from rich.console import Group, RenderableType
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.text import Text

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
    display_content: list[DisplayItem] | None,
    mode: Mode | Literal["diff", "conversation", "raw"],
    unified_diff: str | None,
) -> str:
    """
    Reconstructs the final string content to print to stdout for non-TTY (piped) output,
    ensuring the contract for each mode is respected.
    """
    # Strict contract for 'gen' (diff) mode: only print the unified diff; otherwise empty.
    if (mode.value if isinstance(mode, Mode) else str(mode)) == "diff":
        return unified_diff or ""

    # Flexible contract for other modes: prefer a valid diff, else fall back to display content.
    if unified_diff:
        return unified_diff

    if display_content:
        return "".join(item["content"] for item in display_content)

    return ""


def display_cost_summary(
    token_usage: TokenUsage,
    cost: float | None,
    session_data: SessionData,
) -> None:
    """Displays token/cost information to stderr (or formatted TTY)."""
    prompt_tokens_str = format_tokens(token_usage.prompt_tokens)
    if token_usage.cached_tokens:
        prompt_tokens_str += f" ({format_tokens(token_usage.cached_tokens)} cached)"

    completion_tokens_str = format_tokens(token_usage.completion_tokens)
    if token_usage.reasoning_tokens:
        completion_tokens_str += f" ({format_tokens(token_usage.reasoning_tokens)} reasoning)"

    cost_str: str = ""
    if cost is not None:
        # Calculate window history cost using absolute indices
        active_pairs = get_active_message_pairs(session_data)

        window_history_cost = 0.0
        for _, pair in active_pairs:
            match session_data.chat_history[pair.assistant_index]:
                case AssistantChatMessage(cost=float(historical_cost)):
                    window_history_cost += historical_cost
                case _:
                    pass

        total_window_cost = window_history_cost + cost
        cost_str = f"Cost: ${cost:.2f}, current chat: ${total_window_cost:.2f}"

    info_str = f"Tokens: {prompt_tokens_str} sent, {completion_tokens_str} received. {cost_str}"

    if is_terminal():
        from rich.console import Console

        console = Console()
        console.print(f"\n[dim]---[/dim]\n[dim]{info_str}[/dim]")
    else:
        print(info_str, file=sys.stderr)
