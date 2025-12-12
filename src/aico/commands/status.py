import json
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from aico.historystore.pointer import InvalidPointerError, MissingViewError, load_pointer
from aico.llm.tokens import (
    compute_component_cost,
    count_active_history_tokens,
    count_context_files_tokens,
    count_max_alignment_tokens,
    count_system_tokens,
)
from aico.model_registry import get_model_info
from aico.models import ContextFilesResponse, SessionData, TokenInfo
from aico.session_context import build_active_context, summarize_active_window
from aico.session_loader import load_active_session


def _get_session_name(session_file: Path) -> str | None:
    """
    Returns the current session/view name for shared-history sessions.
    For legacy sessions (no pointer or invalid pointer), returns None.
    """
    try:
        view_path = load_pointer(session_file)
    except (InvalidPointerError, MissingViewError, OSError):
        # Legacy or invalid pointer: omit a name for status display.
        return None
    return view_path.stem


def _format_cost(cost: float | None) -> str:
    """Formats cost for display, handling explicit zero costs."""
    if cost is None:
        return ""
    # Standardize explicit zero cost display to avoid ".0000"
    if cost == 0.0:
        return "$0.0000"
    return f"${cost:,.5f}"


def _get_history_summary_text(session_data: SessionData) -> Text | None:
    summary = summarize_active_window(session_data)
    if summary is None:
        return None
    if summary.active_pairs == 0 and summary.has_active_dangling:
        return Text("  └─ Active context contains partial/dangling messages.", style="dim")
    plural_s = "s" if summary.active_pairs != 1 else ""
    window_id_str: str = ""
    if summary.has_any_active_history:
        window_id_str = (
            f"ID {summary.active_start_id}"
            if summary.active_start_id == summary.active_end_id
            else f"IDs {summary.active_start_id}-{summary.active_end_id}"
        )
    else:
        window_id_str = "No IDs"

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


def status(json_output: bool = False) -> None:  # noqa: C901
    session = load_active_session()

    if json_output:
        response: ContextFilesResponse = {
            "context_files": sorted(session.data.context_files),
        }
        print(json.dumps(response))
        return

    console = Console()

    # Resolve context once for consistent token counting
    context = build_active_context(session.data)

    model_name = session.data.model

    components: list[TokenInfo] = []

    # 1. System Prompt
    sys_tokens = count_system_tokens(model_name)
    components.append(TokenInfo(description="system prompt", tokens=sys_tokens))

    # 2. Alignment Prompts (worst-case)
    align_tokens = count_max_alignment_tokens(model_name)
    if align_tokens > 0:
        components.append(TokenInfo(description="alignment prompts (worst-case)", tokens=align_tokens))

    # 3. Chat History
    history_tokens = count_active_history_tokens(model_name, context["active_history"])
    history_component = TokenInfo(description="chat history", tokens=history_tokens)

    # 4. Context Files
    file_components, skipped_files = count_context_files_tokens(model_name, session.data, session.root)
    if skipped_files:
        skipped_list = " ".join(sorted(skipped_files))
        console.print(f"[yellow]Warning: Context files not found, skipped: {skipped_list}[/yellow]")

    # 5. Cost Calculation
    all_components_with_tokens = components + [history_component] + file_components
    total_tokens = sum(c.tokens for c in all_components_with_tokens)
    total_cost = 0.0
    has_cost_info = False

    model_info = get_model_info(model_name)
    for component in all_components_with_tokens:
        component.cost = compute_component_cost(model_info, component.tokens)
        if component.cost is not None:
            total_cost += component.cost

    if model_info.input_cost_per_token is not None or model_info.output_cost_per_token is not None:
        has_cost_info = True

    # 6. Context Window Info
    max_input_tokens: int | None = model_info.max_input_tokens

    # --- Rich Rendering ---
    session_name = _get_session_name(session.file_path) or "main"

    header_title = f"Session '{session_name}'"
    header_body = Text(session.data.model, justify="center")

    console.print(Panel(header_body, title=header_title, border_style="dim"))
    console.print()

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=8, justify="right")
    table.add_column(width=11, justify="right")
    table.add_column(no_wrap=True, overflow="ellipsis")

    table.add_row(Text("Tokens (approx.)", style="bold"), Text("Cost", style="bold"), Text("Component", style="bold"))
    table.add_row(Rule(style="dim"), Rule(style="dim"), Rule(style="dim"))

    for component in components:
        table.add_row(
            f"{component.tokens:,}",
            _format_cost(component.cost) if has_cost_info else "",
            component.description,
        )

    table.add_row(
        f"{history_component.tokens:,}" if history_component.tokens > 0 else "",
        _format_cost(history_component.cost) if has_cost_info else "",
        history_component.description,
    )

    if history_summary_text := _get_history_summary_text(session.data):
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
                _format_cost(component.cost) if has_cost_info else "",
                component.description,
            )

    table.add_row(Rule(style="dim"), Rule(style="dim"), Rule(style="dim"))
    table.add_row(
        Text(f"~{total_tokens:,}", style="bold"),
        Text(_format_cost(total_cost), style="bold") if has_cost_info else "",
        Text("Total", style="bold"),
    )

    console.print(table, markup=False)

    if max_input_tokens:
        console.print()
        progress = ProgressBar(total=max_input_tokens, completed=total_tokens)

        remaining_tokens = max_input_tokens - total_tokens
        remaining_percent = (remaining_tokens / max_input_tokens * 100) if max_input_tokens > 0 else 0

        summary_text = Text(
            f"({total_tokens:,} of {max_input_tokens:,} used - {remaining_percent:.0f}% remaining)", justify="center"
        )

        console.print(Panel(Group(summary_text, progress), title="Context Window", border_style="dim"))
