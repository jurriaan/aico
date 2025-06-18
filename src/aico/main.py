import difflib
import sys
from collections.abc import Iterable
from pathlib import Path

import litellm
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markdown import Markdown

from aico.models import ChatMessage, LastResponse, Mode, SessionData
from aico.utils import SESSION_FILE_NAME, find_session_file

app = typer.Typer()


@app.command()
def init() -> None:
    """
    Initializes a new AI session in the current directory.
    """
    existing_session_file = find_session_file()
    if existing_session_file:
        print(
            f"Error: An existing session was found at '{existing_session_file}'. "
            f"Please run commands from that directory or its subdirectories.",
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

    new_session = SessionData()
    session_file.write_text(new_session.model_dump_json(indent=2))

    print(f"Initialized session file: {session_file}")


@app.command()
def last() -> None:
    """
    Prints the last processed response from the AI to standard output.
    """
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. "
            "Please run 'aico init' first.",
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

    if not session_data.last_response:
        print("Error: No last response found in session.", file=sys.stderr)
        raise typer.Exit(code=1)

    print(session_data.last_response.processed_content)


@app.command()
def add(file_path: Path) -> None:
    """
    Adds a file to the context for the AI session.
    """
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. "
            "Please run 'aico init' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    session_root = session_file.parent

    if not file_path.is_file():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        raise typer.Exit(code=1)

    abs_file_path = file_path.resolve()

    try:
        relative_path = abs_file_path.relative_to(session_root)
    except ValueError:
        print(
            f"Error: File '{file_path}' is outside the session root '{session_root}'. "
            "Files must be within the same directory tree as the session file.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    relative_path_str = str(relative_path)

    try:
        session_data = SessionData.model_validate_json(session_file.read_text())
    except ValidationError:
        print(
            "Error: Session file is corrupt or has an invalid format.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    if relative_path_str not in session_data.context_files:
        session_data.context_files.append(relative_path_str)
        _ = session_file.write_text(session_data.model_dump_json(indent=2))
        print(f"Added file to context: {relative_path_str}")
    else:
        print(f"File already in context: {relative_path_str}")


def translate_response_to_diff(
    original_file_contents: dict[str, str], llm_response: str
) -> str:
    """
    Parses the LLM's SEARCH/REPLACE response and generates a unified diff.
    """
    lines: list[str] = llm_response.strip().splitlines()

    file_path_str: str | None = None
    if lines and lines[0].startswith("File: "):
        file_path_str = lines[0][len("File: ") :].strip()
        lines = lines[1:]  # consume the file path line
    else:
        return "Error: Could not parse LLM response. 'File: ' marker not found."

    try:
        search_start_index = lines.index("<<<<<<< SEARCH")
        divider_index = lines.index("=======")
        replace_end_index = lines.index(">>>>>>> REPLACE")
    except ValueError:
        return (
            "Error: Could not parse LLM response. SEARCH/REPLACE markers not found."
            f"\n--- Response ---\n{llm_response}\n---"
        )

    search_block = "\n".join(lines[search_start_index + 1 : divider_index])
    replace_block = "\n".join(lines[divider_index + 1 : replace_end_index])

    if file_path_str not in original_file_contents:
        return (
            f"Error: LLM specified a file not in the context: {file_path_str}\n"
            f"Available files: {list(original_file_contents.keys())}"
        )

    original_content = original_file_contents[file_path_str]

    if search_block not in original_content:
        # To help debug, show a diff between what the LLM wanted to find and the file.
        search_diff = "".join(
            difflib.unified_diff(
                search_block.splitlines(keepends=True),
                original_content.splitlines(keepends=True),
                fromfile="llm_search_block",
                tofile="original_file_content",
            )
        )
        return (
            "Error: The SEARCH block from the LLM response was not found in the original file.\n"
            f"--- Diff of SEARCH block vs Original File ---\n{search_diff}"
        )

    # Perform a single replacement
    new_content = original_content.replace(search_block, replace_block, 1)

    # Generate a diff with relative paths for compatibility with 'git apply'
    relative_path = Path(file_path_str)  # The path from the LLM is now relative

    diff: Iterable[str] = difflib.unified_diff(
        original_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
    )

    return "".join(diff)


@app.command()
def prompt(
    prompt_text: str,
    system_prompt: str = typer.Option(
        "You are an expert pair programmer.", help="The system prompt to guide the AI."
    ),
    mode: Mode = typer.Option(
        Mode.RAW,
        help="Output mode: 'raw' for plain text, 'diff' for git diff.",
        case_sensitive=False,
    ),
) -> None:
    """
    Sends a prompt to the AI with the current context.
    """
    # 1. Load State
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. "
            "Please run 'aico init' first.",
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
            "IMPORTANT: You must format your response as a single, raw SEARCH/REPLACE block. "
            "Do not add any other text, commentary, or markdown code fences. "
            "The required format is:\n"
            "File: path/to/the/file.ext\n"
            "<<<<<<< SEARCH\n"
            "The exact lines of code to be replaced.\n"
            "=======\n"
            "The new lines of code to be inserted.\n"
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

    messages.extend([msg.model_dump() for msg in session_data.chat_history])
    messages.append({"role": "user", "content": user_prompt_xml})

    # 5. Call LLM
    try:
        # Using a general-purpose, fast model.
        response = litellm.completion(
            model="openrouter/google/gemini-2.5-flash",
            messages=messages,
        )
        llm_response_content = response.choices[0].message.content or ""
    except Exception as e:
        print(f"Error calling LLM API: {e}", file=sys.stderr)
        raise typer.Exit(code=1)

    # 6. Process Output Based on Mode
    processed_content: str
    if mode == Mode.RAW:
        processed_content = llm_response_content
    elif mode == Mode.DIFF:
        processed_content = translate_response_to_diff(
            original_file_contents, llm_response_content
        )

    # 7. Update State
    # Save the raw user prompt, not the full XML, to keep history clean.
    session_data.chat_history.append(
        ChatMessage(role="user", content=prompt_text, mode=mode)
    )
    session_data.chat_history.append(
        ChatMessage(role="assistant", content=llm_response_content, mode=mode)
    )
    session_data.last_response = LastResponse(
        raw_content=llm_response_content,
        mode_used=mode,
        processed_content=processed_content,
    )

    session_file.write_text(session_data.model_dump_json(indent=2))

    # 8. Print Final Output
    # If outputting in raw mode to an interactive terminal, format as markdown.
    if mode == Mode.RAW and sys.stdout.isatty():
        console = Console()
        console.print(Markdown(processed_content))
    else:
        # Otherwise, print raw content (for piping or diff mode).
        print(processed_content)


if __name__ == "__main__":
    app()
