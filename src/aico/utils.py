import os
import sys
from json import JSONDecodeError
from pathlib import Path
from tempfile import mkstemp

import typer
from pydantic import TypeAdapter, ValidationError
from rich.console import Console

from aico.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    LLMChatMessage,
    SessionData,
    TokenUsage,
    UserChatMessage,
)

SESSION_FILE_NAME = ".ai_session.json"


def find_session_file() -> Path | None:
    """
    Finds the .ai_session.json file by searching upward from the current directory.
    """
    current_dir = Path.cwd().resolve()
    while True:
        session_file = current_dir / SESSION_FILE_NAME
        if session_file.is_file():
            return session_file
        if current_dir.parent == current_dir:  # Reached the filesystem root
            return None
        current_dir = current_dir.parent


def format_tokens(tokens: int) -> str:
    """Formats token counts for display, using 'k' for thousands."""
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


SessionDataAdapter = TypeAdapter(SessionData)


def load_session() -> tuple[Path, SessionData]:
    session_file = find_session_file()
    if not session_file:
        print(
            f"Error: No session file '{SESSION_FILE_NAME}' found. Please run 'aico init' first.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    try:
        session_data = SessionDataAdapter.validate_json(session_file.read_text())

    except ValidationError:
        print(
            "Error: Session file is corrupt or has an invalid format.", file=sys.stderr
        )
        raise typer.Exit(code=1)

    return session_file, session_data


def get_relative_path_or_error(file_path: Path, session_root: Path) -> str | None:
    abs_file_path = file_path.resolve()

    try:
        relative_path = abs_file_path.relative_to(session_root)
        return str(relative_path)
    except ValueError:
        print(
            f"Error: File '{abs_file_path}' is outside the session root '{session_root}'. Files must be within the same directory tree as the session file.",
            file=sys.stderr,
        )
        return None


def is_terminal() -> bool:
    """Checks if stdout is a TTY."""
    return sys.stdout.isatty()


def reconstruct_historical_messages(
    history: list[ChatMessageHistoryItem],
) -> list[LLMChatMessage]:
    reconstructed: list[LLMChatMessage] = []
    for msg in history:
        reconstructed_msg: LLMChatMessage
        match msg:
            case UserChatMessage(content=str(prompt), piped_content=str(piped_content)):
                reconstructed_msg = {
                    "role": "user",
                    "content": (
                        f"<stdin_content>\n{piped_content}\n</stdin_content>\n"
                        + f"<prompt>\n{prompt}\n</prompt>"
                    ),
                }
            case UserChatMessage(content=str(prompt)):
                reconstructed_msg = {
                    "role": "user",
                    "content": f"<prompt>\n{msg.content}\n</prompt>",
                }
            case AssistantChatMessage(content=str(content)):
                reconstructed_msg = {"role": "assistant", "content": content}

        reconstructed.append(reconstructed_msg)
    return reconstructed


def calculate_and_display_cost(
    token_usage: TokenUsage, session_data: SessionData
) -> float | None:
    """Calculates the message cost and displays token/cost information."""
    import litellm

    message_cost: float | None = None
    # Create a mock response object as a dictionary.
    # This provides litellm.completion_cost with the usage data AND the model name
    # in a format it expects for calculating costs robustly.
    mock_response = {
        "usage": {
            "prompt_tokens": token_usage.prompt_tokens,
            "completion_tokens": token_usage.completion_tokens,
            "total_tokens": token_usage.total_tokens,
        },
        "model": session_data.model,
    }

    try:
        message_cost = litellm.completion_cost(completion_response=mock_response)  # pyright: ignore[reportUnknownMemberType, reportPrivateImportUsage]
    except Exception as _:
        pass

    prompt_tokens_str = format_tokens(token_usage.prompt_tokens)
    completion_tokens_str = format_tokens(token_usage.completion_tokens)

    cost_str: str = ""
    if message_cost is not None:
        history_cost = sum(
            msg.cost
            for msg in session_data.chat_history
            if isinstance(msg, AssistantChatMessage) and msg.cost is not None
        )
        session_cost = history_cost + message_cost
        cost_str = f"Cost: ${message_cost:.2f} message, ${session_cost:.2f} session."

    info_str = f"Tokens: {prompt_tokens_str} sent, {completion_tokens_str} received. {cost_str}"

    if is_terminal():
        console = Console()
        console.print(f"\n[dim]---[/dim]\n[dim]{info_str}[/dim]")
    else:
        print(info_str, file=sys.stderr)

    return message_cost


def complete_files_in_context(incomplete: str) -> list[str]:
    session_file = find_session_file()
    if not session_file:
        return []

    try:
        session_data = SessionDataAdapter.validate_json(session_file.read_text())
        completions = [
            f for f in session_data.context_files if f.startswith(incomplete)
        ]
        completions += [
            f
            for f in session_data.context_files
            if incomplete in f and f not in completions
        ]
        return completions
    except (ValidationError, JSONDecodeError):
        return []


def save_session(session_file: Path, session_data: SessionData) -> None:
    fd, tmp = mkstemp(
        suffix=".json", prefix=session_file.name + ".tmp", dir=session_file.parent
    )
    session_file_tmp = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as f:
            _ = f.write(SessionDataAdapter.dump_json(session_data, indent=2))
        os.replace(session_file_tmp, session_file)
    finally:
        session_file_tmp.unlink(missing_ok=True)
