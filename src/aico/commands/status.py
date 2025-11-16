from contextlib import suppress
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from aico.core.session_context import summarize_active_window
from aico.core.session_persistence import get_persistence
from aico.historystore.pointer import InvalidPointerError, MissingViewError, load_pointer
from aico.lib.models import SessionData, TokenInfo
from aico.utils import (
    compute_component_cost,
    count_active_history_tokens,
    count_context_files_tokens,
    count_max_alignment_tokens,
    count_system_tokens,
)


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

    model = session_data.model

    components: list[TokenInfo] = []

    # 1. System Prompt
    sys_tokens = count_system_tokens(model)
    components.append(TokenInfo(description="system prompt", tokens=sys_tokens))

    # 2. Alignment Prompts (worst-case)
    align_tokens = count_max_alignment_tokens(model)
    if align_tokens > 0:
        components.append(TokenInfo(description="alignment prompts (worst-case)", tokens=align_tokens))

    # 3. Chat History
    history_tokens = count_active_history_tokens(model, session_data)
    history_component = TokenInfo(description="chat history", tokens=history_tokens)

    # 4. Context Files
    file_components, skipped_files = count_context_files_tokens(model, session_data, session_root)
    if skipped_files:
        skipped_list = " ".join(sorted(skipped_files))
        console.print(f"[yellow]Warning: Context files not found, skipped: {skipped_list}[/yellow]")

    # 5. Cost Calculation
    import litellm
    from litellm.router import ModelInfo  # pyright: ignore[reportPrivateImportUsage]

    all_components_with_tokens = components + [history_component] + file_components
    total_tokens = sum(c.tokens for c in all_components_with_tokens)
    total_cost = 0.0
    has_cost_info = False
    model_info: ModelInfo | None = None

    with suppress(Exception):
        model_info = litellm.get_model_info(model)  # pyright: ignore[reportPrivateImportUsage]

    has_cost_info = bool(model_info and model_info.get("input_cost_per_token", 0) > 0)

    if has_cost_info:
        for component in all_components_with_tokens:
            component.cost = compute_component_cost(model, component.tokens)
            if component.cost is not None:
                total_cost += component.cost

    # 6. Context Window Info
    max_input_tokens: int | None = model_info.get("max_input_tokens") if model_info else None

    # --- Rich Rendering ---
    session_name = _get_session_name(session_file) or "main"

    header_title = f"Session '{session_name}'"
    header_body = Text(session_data.model, justify="center")

    console.print(Panel(header_body, title=header_title, border_style="dim"))
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
