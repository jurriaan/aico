import litellm
import typer
from rich.console import Console
from rich.table import Table

from aico.utils import load_session

tokens_app = typer.Typer(
    help="Commands for inspecting prompt token usage and costs.",
)


@tokens_app.callback(invoke_without_command=True)
def tokens() -> None:
    """
    Calculates and displays the token usage and cost for the current session context.
    """
    session_file, session_data = load_session()
    session_root = session_file.parent

    console = Console()

    # Base system prompt + diff mode instructions (worst-case scenario for tokens)
    system_prompt = (
        "You are an expert pair programmer."
        "\n\n---\n"
        "IMPORTANT: You are an automated code generation tool. Your response MUST ONLY contain one or more raw SEARCH/REPLACE blocks. "
        "You MUST NOT add any other text, commentary, or markdown. "
        "Your entire response must strictly follow the format specified below.\n"
        "- To create a new file, use an empty SEARCH block.\n"
        "- To delete a file, provide a SEARCH block with the entire file content and an empty REPLACE block.\n\n"
        "EXAMPLE of a multi-file change:\n"
        "File: path/to/existing/file.py\n"
        "<<<<<<< SEARCH\n"
        "    # code to be changed\n"
        "=======\n"
        "    # the new code\n"
        ">>>>>>> REPLACE\n"
        "File: path/to/new/file.py\n"
        "<<<<<<< SEARCH\n"
        "=======\n"
        "def new_function():\n"
        "    pass\n"
        ">>>>>>> REPLACE"
    )

    components = []
    total_tokens = 0

    # 1. System Prompt Tokens
    system_prompt_tokens = litellm.token_counter(
        model=session_data.model, text=system_prompt
    )
    components.append({"description": "system prompt", "tokens": system_prompt_tokens})
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
            {
                "description": "chat history",
                "tokens": history_tokens,
                "note": "(use 'aico history' to manage)",
            }
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
                {
                    "description": file_path_str,
                    "tokens": file_tokens,
                    "note": "(use 'aico drop' to remove)",
                }
            )
            total_tokens += file_tokens
        except FileNotFoundError:
            # If a file in context is not found, we ignore it for token counting.
            # The main `prompt` command would show a warning.
            pass

    # After collecting all components, calculate costs
    total_cost = 0.0
    has_cost_info = False

    # Check for cost info *once* using a dummy call with the correct format,
    # mimicking the structure used in main.py.
    dummy_response = {
        "usage": {"prompt_tokens": 1, "completion_tokens": 0},
        "model": session_data.model,
    }
    if litellm.completion_cost(completion_response=dummy_response) is not None:
        has_cost_info = True

    if has_cost_info:
        for item in components:
            # We only have prompt tokens, so completion_tokens is 0.
            mock_response = {
                "usage": {
                    "prompt_tokens": item["tokens"],
                    "completion_tokens": 0,
                    "total_tokens": item["tokens"],
                },
                "model": session_data.model,
            }
            cost = litellm.completion_cost(completion_response=mock_response)
            item["cost"] = cost if cost is not None else 0.0
            total_cost += item["cost"]


    # Display results
    console.print(
        f"Approximate context window usage for {session_data.model}, in tokens:\n"
    )
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(justify="right")  # Tokens
    if has_cost_info:
        table.add_column(justify="right")  # Cost
    table.add_column()  # Description
    table.add_column(style="dim")  # Note

    for item in components:
        row_items = [f"{item['tokens']:,}"]
        if has_cost_info:
            cost = item.get("cost", 0.0)
            # Use 5 decimal places for precision on small costs
            row_items.append(f"${cost:.5f}")
        row_items.append(item["description"])
        row_items.append(item.get("note", ""))
        table.add_row(*row_items)

    console.print(table)

    # Use a rule for the separator
    separator_len = 22
    if has_cost_info:
        separator_len += 12  # Account for cost column + padding
    console.print("=" * separator_len)

    total_table = Table(show_header=False, box=None, padding=(0, 2))
    total_table.add_column(justify="right")  # Tokens
    if has_cost_info:
        total_table.add_column(justify="right")  # Cost
    total_table.add_column()  # "total" label

    total_row = [f"{total_tokens:,}"]
    if has_cost_info:
        total_row.append(f"${total_cost:.5f}")
    total_row.append("total")

    total_table.add_row(*total_row)
    console.print(total_table)
