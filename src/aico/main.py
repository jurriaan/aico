import sys
import warnings
import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from aico.diffing import (
    generate_display_content,
    generate_unified_diff,
)
from aico.history import history_app
from aico.models import ChatMessage, LastResponse, Mode, SessionData, TokenUsage
from aico.utils import SESSION_FILE_NAME, find_session_file, format_tokens

app = typer.Typer()
app.add_typer(history_app, name="history")


# Workaround for `no_args_is_help` not working, keep this until #1240 in typer is fixed
# CANNOT BE REMOVED!
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        raise typer.Exit()


@app.command()
def init(
    model: Annotated[
        str,
        typer.Option(
            ...,
            "--model",
            "-m",
            help="The model to use for the session.",
        ),
    ] = "openrouter/google/gemini-2.5-pro",
) -> None:
    """
    Initializes a new AI session in the current directory.
    """
    existing_session_file = find_session_file()
    if existing_session_file:
        print(
            f"Error: An existing session was found at '{existing_session_file}'. Please run commands from that directory or its subdirectories.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    session_file = Path.cwd() / SESSION_FILE_NAME
    if session_file.exists():
        print(
            f"Error: Session file '{session_file}' already exists in this directory.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    new_session = SessionData(model=model)
    _ = session_file.write_text(new_session.model_dump_json(indent=2))

    print(f"Initialized session file: {session_file}")


@app.command()
def last() -> None:
    """
    Prints the last processed response from the AI to standard output.
    """
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. Please run 'aico init' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    try:
        session_data = SessionData.model_validate_json(session_file.read_text())
    except ValidationError:
        print(
            "Error: Session file is corrupt or has an invalid format.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    last_resp = session_data.last_response
    if not last_resp:
        print("Error: No last response found in session.", file=sys.stderr)
        raise typer.Exit(code=1)

    if last_resp.mode_used == Mode.RAW:
        # In RAW mode, raw_content is the single source of truth.
        content = last_resp.raw_content
        if sys.stdout.isatty():
            from rich.console import Console
            from rich.markdown import Markdown

            console = Console()
            console.print(Markdown(content))
        else:
            print(content)

    elif last_resp.mode_used == Mode.DIFF:
        # In DIFF mode, we choose between two different derived representations.
        if sys.stdout.isatty():
            # For interactive terminals, show the rich display content.
            if last_resp.display_content:
                from rich.console import Console
                from rich.markdown import Markdown

                console = Console()
                console.print(Markdown(last_resp.display_content))
        else:
            # For pipes, print the clean, machine-readable diff.
            if last_resp.unified_diff:
                print(last_resp.unified_diff)


@app.command()
def add(file_paths: list[Path]) -> None:
    """
    Adds one or more files to the context for the AI session.
    """
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. Please run 'aico init' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    session_root = session_file.parent

    try:
        session_data = SessionData.model_validate_json(session_file.read_text())
    except ValidationError:
        print(
            "Error: Session file is corrupt or has an invalid format.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    files_were_added = False
    errors_found = False

    for file_path in file_paths:
        if not file_path.is_file():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            errors_found = True
            continue

        abs_file_path = file_path.resolve()

        try:
            relative_path = abs_file_path.relative_to(session_root)
        except ValueError:
            print(
                f"Error: File '{abs_file_path}' is outside the session root '{session_root}'. Files must be within the same directory tree as the session file.",
                file=sys.stderr,
            )
            errors_found = True
            continue

        relative_path_str = str(relative_path)

        if relative_path_str not in session_data.context_files:
            session_data.context_files.append(relative_path_str)
            files_were_added = True
            print(f"Added file to context: {relative_path_str}")
        else:
            print(f"File already in context: {relative_path_str}")

    if files_were_added:
        session_data.context_files.sort()
        _ = session_file.write_text(session_data.model_dump_json(indent=2))

    if errors_found:
        raise typer.Exit(code=1)


def complete_files_in_context(incomplete: str) -> list[str]:
    session_file = find_session_file()
    if not session_file:
        return []

    try:
        session_data = SessionData.model_validate_json(session_file.read_text())
        completions = [f for f in session_data.context_files if f.startswith(incomplete)]
        return completions
    except (ValidationError, json.JSONDecodeError):
        return []


@app.command()
def drop(
    file_paths: Annotated[
        list[Path],
        typer.Argument(autocompletion=complete_files_in_context),
    ]
) -> None:
    """
    Drops one or more files from the context for the AI session.
    """
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. Please run 'aico init' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    session_root = session_file.parent

    try:
        session_data = SessionData.model_validate_json(session_file.read_text())
    except ValidationError:
        print(
            "Error: Session file is corrupt or has an invalid format.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    files_were_dropped = False
    errors_found = False

    new_context_files = session_data.context_files[:]

    for file_path in file_paths:
        abs_file_path = file_path.resolve()

        try:
            relative_path_str = str(abs_file_path.relative_to(session_root))
        except ValueError:
            print(f"Error: File not in context: {file_path}", file=sys.stderr)
            errors_found = True
            continue

        if relative_path_str in new_context_files:
            new_context_files.remove(relative_path_str)
            files_were_dropped = True
            print(f"Dropped file from context: {relative_path_str}")
        else:
            print(f"Error: File not in context: {file_path}", file=sys.stderr)
            errors_found = True

    if files_were_dropped:
        session_data.context_files = sorted(new_context_files)
        _ = session_file.write_text(session_data.model_dump_json(indent=2))

    if errors_found:
        raise typer.Exit(code=1)


@app.command()
def prompt(
    prompt_text: str,
    system_prompt: Annotated[
        str, typer.Option(help="The system prompt to guide the AI.")
    ] = "You are an expert pair programmer.",
    mode: Annotated[
        Mode,
        typer.Option(
            help="Output mode: 'raw' for plain text, 'diff' for git diff.",
            case_sensitive=False,
        ),
    ] = Mode.RAW,
) -> None:
    """
    Sends a prompt to the AI with the current context.
    """
    # 1. Load State
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. Please run 'aico init' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    session_root = session_file.parent
    try:
        session_data = SessionData.model_validate_json(session_file.read_text())
    except ValidationError:
        print(
            "Error: Session file is corrupt or has an invalid format.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    # 2. Prepare System Prompt
    if mode == Mode.DIFF:
        formatting_rule = (
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
        system_prompt += formatting_rule

    # 3. Construct User Prompt
    context_str = "<context>\n"
    original_file_contents = {}
    for relative_path_str in session_data.context_files:
        try:
            # Reconstruct absolute path to read the file
            abs_path = session_root / relative_path_str
            content = abs_path.read_text()
            # Key the contents by the relative path
            original_file_contents[relative_path_str] = content
            # Send the relative path to the LLM
            context_str += f'  <file path="{relative_path_str}">\n{content}\n</file>\n'
        except FileNotFoundError:
            print(
                f"Warning: Context file not found, skipping: {relative_path_str}",
                file=sys.stderr,
            )
    context_str += "</context>\n"

    user_prompt_xml = f"{context_str}<prompt>\n{prompt_text}\n</prompt>"

    # 4. Construct Messages
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    active_history = session_data.chat_history[session_data.history_start_index :]
    messages.extend(
        [{"role": msg.role, "content": msg.content} for msg in active_history]
    )
    messages.append({"role": "user", "content": user_prompt_xml})

    # 5. Call LLM
    import litellm

    try:
        # Suppress Pydantic warnings that can occur internally within litellm.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            response = litellm.completion(
                model=session_data.model,
                messages=messages,
            )
            llm_response_content: str = response.choices[0].message.content or ""
    except Exception as e:
        print(f"Error calling LLM API: {e}", file=sys.stderr)
        raise typer.Exit(code=1)

    token_usage: TokenUsage | None = None
    message_cost: float | None = None

    if response.usage:
        token_usage = TokenUsage(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        )
        # litellm can return a float or None
        message_cost = litellm.completion_cost(completion_response=response) or 0.0

        prompt_tokens_str = format_tokens(token_usage.prompt_tokens)
        completion_tokens_str = format_tokens(token_usage.completion_tokens)

        cost_str: str
        history_cost = sum(
            msg.cost
            for msg in session_data.chat_history
            if msg.role == "assistant" and msg.cost is not None
        )
        session_cost = history_cost + message_cost
        cost_str = f"Cost: ${message_cost:.2f} message, ${session_cost:.2f} session."

        print(
            f"Tokens: {prompt_tokens_str} sent, {completion_tokens_str} received. {cost_str}",
            file=sys.stderr,
        )

    # 6. Process Output Based on Mode
    unified_diff: str | None = None
    display_content: str | None = None
    if mode == Mode.DIFF:
        unified_diff = generate_unified_diff(
            original_file_contents, llm_response_content
        )
        print(unified_diff, file=sys.stderr)
        display_content = generate_display_content(
            original_file_contents, llm_response_content
        )

    # 7. Update State
    # Save the raw user prompt, not the full XML, to keep history clean.
    session_data.chat_history.append(
        ChatMessage(role="user", content=prompt_text, mode=mode)
    )
    session_data.chat_history.append(
        ChatMessage(
            role="assistant",
            content=llm_response_content,
            mode=mode,
            token_usage=token_usage,
            cost=message_cost,
        )
    )
    session_data.last_response = LastResponse(
        raw_content=llm_response_content,
        mode_used=mode,
        unified_diff=unified_diff,
        display_content=display_content,
        token_usage=token_usage,
        cost=message_cost,
    )

    session_file.write_text(session_data.model_dump_json(indent=2))

    # 8. Print Final Output
    if mode == Mode.RAW:
        # In RAW mode, the raw response is the only content.
        if sys.stdout.isatty():
            from rich.console import Console
            from rich.markdown import Markdown

            console = Console()
            console.print(Markdown(llm_response_content))
        else:
            print(llm_response_content)

    elif mode == Mode.DIFF:
        # In DIFF mode, we choose between the display content or unified diff.
        if sys.stdout.isatty():
            if display_content:
                from rich.console import Console
                from rich.markdown import Markdown

                console = Console()
                console.print(Markdown(display_content))
        else:
            if unified_diff:
                print(unified_diff)


if __name__ == "__main__":
    app()
