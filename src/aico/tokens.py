from typing import Annotated

import litellm
import typer
from rich.console import Console
from rich.table import Table

from aico.models import TokenInfo, TokenReport
from aico.utils import DIFF_MODE_INSTRUCTIONS, load_session

tokens_app = typer.Typer(
    help="Commands for inspecting prompt token usage and costs.",
)


@tokens_app.callback(invoke_without_command=True)
def tokens(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output the report as JSON.")
    ] = False,
) -> None:
    """
    Calculates and displays the token usage and cost for the current session context.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent

    console = Console()

    # Base system prompt + diff mode instructions (worst-case scenario for tokens)
    system_prompt = "You are an expert pair programmer." + DIFF_MODE_INSTRUCTIONS

    components: list[TokenInfo] = []
    total_tokens = 0

    # 1. System Prompt Tokens
    system_prompt_tokens = litellm.token_counter(
        model=session_data.model, text=system_prompt
    )
    components.append(
        TokenInfo(description="system prompt", tokens=system_prompt_tokens)
    )
    total_tokens += system_prompt_tokens

    # 2. Chat History Tokens
    active_history = session_data.chat_history[session_data.history_start_index :]
    if active_history:
        # Convert Pydantic models to dicts for litellm
        history_messages = [
            {"role": msg.role, "content": msg.content} for msg in active_history
        ]
        history_tokens = litellm.token_counter(
            model=session_data.model, messages=history_messages
        )
        components.append(
            TokenInfo(
                description="chat history",
                tokens=history_tokens,
                note="(use 'aico history' to manage)",
            )
        )
        total_tokens += history_tokens

    # 3. Context File Tokens
    for file_path_str in session_data.context_files:
        try:
            file_path = session_root / file_path_str
            content = file_path.read_text()
            # The prompt includes the XML wrapper, so we account for its tokens too
            file_prompt_wrapper = f'<file path="{file_path_str}">\n{content}\n</file>\n'
            file_tokens = litellm.token_counter(
                model=session_data.model, text=file_prompt_wrapper
            )
            components.append(
                TokenInfo(
                    description=file_path_str,
                    tokens=file_tokens,
                    note="(use 'aico drop' to remove)",
                )
            )
            total_tokens += file_tokens
        except FileNotFoundError:
            # If a file in context is not found, we ignore it for token counting.
            # The main `prompt` command would show a warning.
            pass

    # After collecting all components, calculate costs
    total_cost = 0.0
    has_cost_info = False

    dummy_response = {
        "usage": {"prompt_tokens": 1, "completion_tokens": 0},
        "model": session_data.model,
    }
    if litellm.completion_cost(completion_response=dummy_response) is not None:
        has_cost_info = True

    if has_cost_info:
        for component in components:
            mock_response = {
                "usage": {
                    "prompt_tokens": component.tokens,
                    "completion_tokens": 0,
                    "total_tokens": component.tokens,
                },
                "model": session_data.model,
            }
            cost = litellm.completion_cost(completion_response=mock_response)
            component.cost = cost
            if cost:
                total_cost += cost

    # Get context window info
    model_info: litellm.router.ModelInfo = litellm.get_model_info(session_data.model)
    remaining_tokens: int | None = None
    if max_input_tokens := model_info["max_input_tokens"]:
        remaining_tokens = max_input_tokens - total_tokens

    token_report = TokenReport(
        model=session_data.model,
        components=components,
        total_tokens=total_tokens,
        total_cost=total_cost if has_cost_info else None,
        max_input_tokens=max_input_tokens,
        remaining_tokens=remaining_tokens,
    )

    if json_output:
        print(token_report.model_dump_json(indent=2))
        return

    # Display results
    console.print(
        f"Approximate context window usage for {token_report.model}, in tokens:\n"
    )
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(justify="right")  # Tokens
    if has_cost_info:
        table.add_column(justify="right")  # Cost
    table.add_column()  # Description
    table.add_column(style="dim")  # Note

    for item in token_report.components:
        row_items = [f"{item.tokens:,}"]
        if has_cost_info:
            cost = item.cost or 0.0
            row_items.append(f"${cost:.5f}")
        row_items.append(item.description)
        row_items.append(item.note or "")
        table.add_row(*row_items)

    console.print(table)

    separator_len = 22
    if has_cost_info:
        separator_len += 12  # Account for cost column + padding
    console.print("=" * separator_len)

    total_table = Table(show_header=False, box=None, padding=(0, 2))
    total_table.add_column(justify="right")  # Tokens
    if has_cost_info:
        total_table.add_column(justify="right")  # Cost
    total_table.add_column()  # "total" label

    total_row = [f"{token_report.total_tokens:,}"]
    if has_cost_info:
        total_row.append(f"${token_report.total_cost:.5f}")
    total_row.append("total")

    total_table.add_row(*total_row)
    console.print(total_table)

    if token_report.max_input_tokens is not None:
        console.print()
        context_table = Table(show_header=False, box=None, padding=(0, 2))
        context_table.add_column(justify="right")
        context_table.add_column()
        context_table.add_row(f"{token_report.max_input_tokens:,}", "max tokens")

        if (
            token_report.remaining_tokens is not None
            and token_report.remaining_tokens != 0
        ):
            remaining_percent = (
                f"({token_report.remaining_tokens / token_report.max_input_tokens:.0%})"
                if token_report.max_input_tokens > 0
                else ""
            )
            context_table.add_row(
                f"{token_report.remaining_tokens:,}",
                f"remaining tokens {remaining_percent}",
            )
        console.print(context_table)
