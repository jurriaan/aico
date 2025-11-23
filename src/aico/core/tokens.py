"""Token counting and cost estimation utilities."""

from pathlib import Path

from aico.core.prompt_helpers import reconstruct_historical_messages
from aico.lib.models import ChatMessageHistoryItem, LLMChatMessage, ModelInfo, SessionData, TokenInfo
from aico.prompts import ALIGNMENT_PROMPTS, DEFAULT_SYSTEM_PROMPT, DIFF_MODE_INSTRUCTIONS


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
