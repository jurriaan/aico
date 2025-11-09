import sys
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich.prompt import Prompt

from aico.core.llm_executor import execute_interaction
from aico.core.session_persistence import get_persistence
from aico.lib.models import (
    AssistantChatMessage,
    DerivedContent,
    Mode,
    UserChatMessage,
)
from aico.prompts import DEFAULT_SYSTEM_PROMPT
from aico.utils import (
    is_input_terminal,
    is_terminal,
    reconstruct_display_content_for_piping,
)


def _invoke_llm_logic(
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
    persistence = get_persistence()
    session_file, session_data = persistence.load()
    session_root = session_file.parent
    timestamp = datetime.now(UTC).isoformat()

    primary_prompt: str
    secondary_piped_content: str | None = None
    piped_input: str | None = None
    if not is_input_terminal():
        content = sys.stdin.read()
        if content:
            piped_input = content

    if cli_prompt_text and piped_input:
        primary_prompt = cli_prompt_text
        secondary_piped_content = piped_input
    elif piped_input:
        primary_prompt = piped_input
    elif cli_prompt_text:
        primary_prompt = cli_prompt_text
    else:
        # No input from CLI or pipe, prompt interactively
        primary_prompt = Prompt.ask("Prompt")
        if not primary_prompt.strip():
            print("Error: Prompt is required.", file=sys.stderr)
            raise typer.Exit(code=1)

    try:
        interaction_result = execute_interaction(
            session_data=session_data,
            system_prompt=system_prompt,
            prompt_text=primary_prompt,
            piped_content=secondary_piped_content,
            mode=mode,
            passthrough=passthrough,
            no_history=no_history,
            session_root=session_root,
            model_override=model,
        )
    except Exception as e:
        print(f"Error calling LLM API: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from e

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
        role="user",
        content=primary_prompt,
        piped_content=secondary_piped_content,
        mode=mode,
        timestamp=timestamp,
        passthrough=passthrough,
    )
    asst_msg = AssistantChatMessage(
        role="assistant",
        content=interaction_result.content,
        mode=mode,
        token_usage=interaction_result.token_usage,
        cost=interaction_result.cost,
        model=model or session_data.model,
        timestamp=assistant_response_timestamp,
        duration_ms=interaction_result.duration_ms,
        derived=derived_content,
    )

    persistence.append_pair(user_msg, asst_msg)

    if not is_terminal():
        if passthrough:
            print(interaction_result.content)
        else:
            output_content = reconstruct_display_content_for_piping(
                interaction_result.display_items, mode, interaction_result.unified_diff
            )
            print(output_content, end="")


def ask(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[str, typer.Option(help="The system prompt to guide the AI.")] = DEFAULT_SYSTEM_PROMPT,
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    no_history: Annotated[
        bool,
        typer.Option(
            "--no-history",
            help="Do not include chat history in the prompt for this request.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Have a conversation for planning and discussion.
    """
    _invoke_llm_logic(cli_prompt_text, system_prompt, Mode.CONVERSATION, passthrough, no_history, model)


def generate_patch(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[str, typer.Option(help="The system prompt to guide the AI.")] = DEFAULT_SYSTEM_PROMPT,
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    no_history: Annotated[
        bool,
        typer.Option(
            "--no-history",
            help="Do not include chat history in the prompt for this request.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Generate code modifications as a unified diff.
    """
    _invoke_llm_logic(cli_prompt_text, system_prompt, Mode.DIFF, passthrough, no_history, model)


def prompt(
    cli_prompt_text: Annotated[str | None, typer.Argument(help="The user's instruction for the AI.")] = None,
    system_prompt: Annotated[str, typer.Option(help="The system prompt to guide the AI.")] = DEFAULT_SYSTEM_PROMPT,
    passthrough: Annotated[
        bool,
        typer.Option(
            help="Send a raw prompt, bypassing all context and formatting.",
        ),
    ] = False,
    no_history: Annotated[
        bool,
        typer.Option(
            "--no-history",
            help="Do not include chat history in the prompt for this request.",
        ),
    ] = False,
    model: Annotated[str | None, typer.Option(help="The model to use for this request")] = None,
) -> None:
    """
    Send a raw prompt to the AI.
    """
    _invoke_llm_logic(cli_prompt_text, system_prompt, Mode.RAW, passthrough, no_history, model)
