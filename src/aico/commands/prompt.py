import sys
from datetime import UTC, datetime

from aico.console import (
    display_cost_summary,
    is_input_terminal,
    is_terminal,
    reconstruct_display_content_for_piping,
)
from aico.exceptions import InvalidInputError, ProviderError
from aico.llm.executor import execute_interaction
from aico.models import (
    AssistantChatMessage,
    DerivedContent,
    Mode,
    UserChatMessage,
)
from aico.session import Session


def run_llm_command(
    cli_prompt_text: str | None,
    system_prompt: str,
    mode: Mode,
    passthrough: bool,
    no_history: bool,
    model: str | None,
) -> None:
    """
    Core logic for invoking the LLM that can be shared by all command wrappers.
    """
    session = Session.load_active()
    timestamp = datetime.now(UTC).isoformat()

    piped_input = sys.stdin.read() if not is_input_terminal() else None

    primary_prompt: str
    secondary_piped_content: str | None = None
    if cli_prompt_text and piped_input:
        primary_prompt = cli_prompt_text
        secondary_piped_content = piped_input
    elif piped_input:
        primary_prompt = piped_input
    elif cli_prompt_text:
        primary_prompt = cli_prompt_text
    else:
        # No input from CLI or pipe, prompt interactively
        from rich.prompt import Prompt

        primary_prompt = Prompt.ask("Prompt")
        if not primary_prompt.strip():
            raise InvalidInputError("Prompt is required.")

    try:
        interaction_result = execute_interaction(
            session_data=session.data,
            system_prompt=system_prompt,
            prompt_text=primary_prompt,
            piped_content=secondary_piped_content,
            mode=mode,
            passthrough=passthrough,
            no_history=no_history,
            session_root=session.root,
            model_override=model,
        )
    except Exception as e:
        raise ProviderError(f"Error calling LLM API: {e}") from e

    assistant_response_timestamp = datetime.now(UTC).isoformat()
    derived_content: DerivedContent | None = None

    # Only create derived content if there is a meaningful diff, or if the structured
    # display items are different from the raw LLM response (e.g., contain warnings or diffs).
    if interaction_result.unified_diff or (
        interaction_result.display_items
        and "".join(item["content"] for item in interaction_result.display_items) != interaction_result.content
    ):
        derived_content = DerivedContent(
            unified_diff=interaction_result.unified_diff, display_content=interaction_result.display_items
        )

    user_msg = UserChatMessage(
        content=primary_prompt,
        piped_content=secondary_piped_content,
        mode=mode,
        timestamp=timestamp,
        passthrough=passthrough,
    )
    asst_msg = AssistantChatMessage(
        content=interaction_result.content,
        mode=mode,
        token_usage=interaction_result.token_usage,
        cost=interaction_result.cost,
        model=model or session.data.model,
        timestamp=assistant_response_timestamp,
        duration_ms=interaction_result.duration_ms,
        derived=derived_content,
    )

    session.append_pair(user_msg, asst_msg)

    if not is_terminal():
        if passthrough:
            print(interaction_result.content)
        else:
            output_content = reconstruct_display_content_for_piping(
                interaction_result.display_items, mode, interaction_result.unified_diff
            )
            print(output_content, end="")
        # Flush stdout before printing diagnostics to stderr
        _ = sys.stdout.flush()

    if interaction_result.token_usage:
        display_cost_summary(interaction_result.token_usage, interaction_result.cost, session.data)
