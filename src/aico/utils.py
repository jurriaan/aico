import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from rich.console import Console, Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text

from aico.core.session_context import get_start_message_index
from aico.lib.model_info import get_model_info
from aico.lib.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    DisplayItem,
    LLMChatMessage,
    Mode,
    ModelInfo,
    SessionData,
    TokenInfo,
    TokenUsage,
    UserChatMessage,
)
from aico.prompts import ALIGNMENT_PROMPTS, DEFAULT_SYSTEM_PROMPT, DIFF_MODE_INSTRUCTIONS


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
    from rich.markdown import Markdown

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


def count_tokens_for_messages(model: str, messages: list[LLMChatMessage]) -> int:  # pyright: ignore[reportUnusedParameter]
    """
    Estimates the number of tokens in a list of messages using a heuristic (chars / 4).
    """
    # Rough estimate: 4 characters per token
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return total_chars // 4


def compute_component_cost(model: ModelInfo, prompt_tokens: int, completion_tokens: int = 0) -> float | None:
    input_cost = model.input_cost_per_token
    output_cost = model.output_cost_per_token

    # If basic input cost information is missing, we can't estimate
    if input_cost is None:
        return None

    cost = prompt_tokens * input_cost

    if completion_tokens > 0:
        if output_cost is not None:
            cost += completion_tokens * output_cost
        else:
            # If we have completion tokens but no output cost, we can't provide a total estimate
            return None

    return cost


def count_system_tokens(model: str) -> int:
    system_prompt = DEFAULT_SYSTEM_PROMPT + DIFF_MODE_INSTRUCTIONS
    return count_tokens_for_messages(model, [{"role": "system", "content": system_prompt}])


def count_max_alignment_tokens(model: str) -> int:
    if not ALIGNMENT_PROMPTS:
        return 0
    max_tokens = max(
        count_tokens_for_messages(model, [{"role": msg.role, "content": msg.content} for msg in prompt_set])
        for prompt_set in ALIGNMENT_PROMPTS.values()
    )
    return max_tokens


def count_active_history_tokens(model: str, active_history: list[ChatMessageHistoryItem]) -> int:
    history_messages = reconstruct_historical_messages(active_history) if active_history else []
    return count_tokens_for_messages(model, history_messages)


def count_context_files_tokens(
    model: str, session_data: SessionData, session_root: Path
) -> tuple[list[TokenInfo], list[str]]:
    file_infos: list[TokenInfo] = []
    skipped_files: list[str] = []
    for file_path_str in session_data.context_files:
        try:
            file_path = session_root / file_path_str
            content = file_path.read_text(encoding="utf-8")
            wrapper = f'<file path="{file_path_str}">\n{content}\n</file>\n'
            tokens = count_tokens_for_messages(model, [{"role": "user", "content": wrapper}])
            file_infos.append(TokenInfo(description=file_path_str, tokens=tokens))
        except OSError:
            # Catches FileNotFoundError, but also other IO errors like broken permissions
            # or symlink loops which should result in the file being skipped/warned.
            skipped_files.append(file_path_str)
    return file_infos, skipped_files
