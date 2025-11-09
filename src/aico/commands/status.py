from contextlib import suppress
from dataclasses import dataclass

from rich.console import Console, Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

import aico.utils as utils
from aico.core.session_context import summarize_active_window
from aico.core.session_persistence import get_persistence
from aico.lib.models import SessionData
from aico.prompts import ALIGNMENT_PROMPTS, DEFAULT_SYSTEM_PROMPT, DIFF_MODE_INSTRUCTIONS


@dataclass(slots=True)
class _TokenInfo:
    description: str
    tokens: int
    cost: float | None = None


def _get_history_summary_text(session_data: SessionData) -> Text | None:
    summary = summarize_active_window(session_data)
    if summary is None:
        return None
    if summary.active_pairs == 0 and summary.has_active_dangling:
        return Text("  └─ Active context contains partial/dangling messages.", style="dim")
    plural_s = "s" if summary.active_pairs != 1 else ""
    window_id_str = (
        f"ID {summary.active_start_id}"
        if summary.active_start_id == summary.active_end_id
        else f"IDs {summary.active_start_id}-{summary.active_end_id}"
    )
    excluded_str = f" ({summary.excluded_in_window} excluded via `aico undo`)" if summary.excluded_in_window else ""
    return Text.assemble(
        ("  └─ ", "dim"),
        (
            (
                f"Active window: {summary.active_pairs} pair{plural_s} ({window_id_str}), "
                f"{summary.pairs_sent} sent{excluded_str}.\n"
            ),
            "dim",
        ),
        ("     (Use `aico log`, `undo`, and `set-history` to manage)", "dim italic"),
    )


def status() -> None:  # noqa: C901
    """
    Show session status and token usage.
    """
    persistence = get_persistence()
    session_file, session_data = persistence.load()
    session_root = session_file.parent
    console = Console()

    components: list[_TokenInfo] = []
    total_tokens = 0

    # 1. System Prompt
    system_prompt = DEFAULT_SYSTEM_PROMPT + DIFF_MODE_INSTRUCTIONS
    system_prompt_tokens = utils.count_tokens_for_messages(
        session_data.model, [{"role": "system", "content": system_prompt}]
    )
    components.append(_TokenInfo(description="system prompt", tokens=system_prompt_tokens))
    total_tokens += system_prompt_tokens

    # 2. Alignment Prompts (worst-case)
    alignment_prompts_tokens = 0
    if ALIGNMENT_PROMPTS:
        alignment_prompts_tokens = max(
            utils.count_tokens_for_messages(
                session_data.model, list({"role": msg.role, "content": msg.content} for msg in ps)
            )
            for ps in ALIGNMENT_PROMPTS.values()
        )
    if alignment_prompts_tokens > 0:
        components.append(_TokenInfo(description="alignment prompts (worst-case)", tokens=alignment_prompts_tokens))
        total_tokens += alignment_prompts_tokens

    # 3. Chat History
    active_history = utils.get_active_history(session_data)
    history_tokens = 0
    if active_history:
        history_messages = utils.reconstruct_historical_messages(active_history)
        history_tokens = utils.count_tokens_for_messages(session_data.model, history_messages)
    history_component = _TokenInfo(description="chat history", tokens=history_tokens)
    total_tokens += history_tokens

    # 4. Context Files
    file_components: list[_TokenInfo] = []
    skipped_files: list[str] = []
    for file_path_str in session_data.context_files:
        try:
            file_path = session_root / file_path_str
            content = file_path.read_text()
            file_prompt_wrapper = f'<file path="{file_path_str}">\n{content}\n</file>\n'
            file_tokens = utils.count_tokens_for_messages(
                session_data.model, [{"role": "user", "content": file_prompt_wrapper}]
            )
            file_components.append(_TokenInfo(description=file_path_str, tokens=file_tokens))
            total_tokens += file_tokens
        except FileNotFoundError:
            _ = skipped_files.append(file_path_str)

    if skipped_files:
        skipped_list = " ".join(sorted(skipped_files))
        console.print(f"[yellow]Warning: Context files not found, skipped: {skipped_list}[/yellow]")

    # 5. Cost Calculation
    import litellm
    from litellm.router import ModelInfo  # pyright: ignore[reportPrivateImportUsage]

    all_components_with_tokens = components + [history_component] + file_components
    total_cost = 0.0
    has_cost_info = False
    model_info: ModelInfo | None = None

    with suppress(Exception):
        model_info = litellm.get_model_info(session_data.model)  # pyright: ignore[reportPrivateImportUsage]

    try:
        if model_info and model_info.get("input_cost_per_token", 0) > 0:
            has_cost_info = True

        if has_cost_info:
            for component in all_components_with_tokens:
                if component.tokens > 0:
                    cost = litellm.completion_cost(  # pyright: ignore[reportPrivateImportUsage, reportUnknownMemberType]
                        completion_response={
                            "usage": {"prompt_tokens": component.tokens, "completion_tokens": 0},
                            "model": session_data.model,
                        }
                    )
                    component.cost = cost
                    total_cost += cost
    except Exception:
        has_cost_info = False

    # 6. Context Window Info
    max_input_tokens: int | None = model_info.get("max_input_tokens") if model_info else None

    # --- Rich Rendering ---
    console.print(Panel(Text(session_data.model, justify="center"), title="Status for model", border_style="dim"))
    console.print()

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=8, justify="right")
    table.add_column(width=11, justify="right")
    table.add_column(no_wrap=True, overflow="ellipsis")

    table.add_row(Text("Tokens", style="bold"), Text("Cost", style="bold"), Text("Component", style="bold"))
    table.add_row(Rule(style="dim"), Rule(style="dim"), Rule(style="dim"))

    for component in components:
        table.add_row(
            f"{component.tokens:,}",
            f"${component.cost:,.5f}" if has_cost_info and component.cost else "",
            component.description,
        )

    table.add_row(
        f"{history_component.tokens:,}" if history_component.tokens > 0 else "",
        f"${history_component.cost:,.5f}" if has_cost_info and history_component.cost else "",
        history_component.description,
    )

    if history_summary_text := _get_history_summary_text(session_data):
        table.add_row("", "", history_summary_text)

    if file_components:
        table.add_row(
            Rule(style="dim"),
            Rule(style="dim"),
            Rule(f"Context Files ({len(file_components)})", style="dim", characters="─"),
        )
        for component in file_components:
            table.add_row(
                f"{component.tokens:,}",
                f"${component.cost:,.4f}" if has_cost_info and component.cost else "",
                component.description,
            )

    table.add_row(Rule(style="dim"), Rule(style="dim"), Rule(style="dim"))
    table.add_row(
        Text(f"{total_tokens:,}", style="bold"),
        Text(f"${total_cost:,.4f}", style="bold") if has_cost_info else "",
        Text("Total", style="bold"),
    )

    console.print(table)

    if max_input_tokens:
        console.print()
        progress = ProgressBar(total=max_input_tokens, completed=total_tokens)

        remaining_tokens = max_input_tokens - total_tokens
        remaining_percent = (remaining_tokens / max_input_tokens * 100) if max_input_tokens > 0 else 0

        summary_text = Text(
            f"({total_tokens:,} of {max_input_tokens:,} used - {remaining_percent:.0f}% remaining)", justify="center"
        )

        console.print(Panel(Group(summary_text, progress), title="Context Window", border_style="dim"))
