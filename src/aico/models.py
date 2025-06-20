from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Mode(str, Enum):
    RAW = "raw"
    DIFF = "diff"


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    mode: Mode
    token_usage: TokenUsage | None = None
    cost: float | None = None


class LastResponse(BaseModel):
    # The verbatim, original response from the LLM. This is the source of truth.
    raw_content: str
    mode_used: Mode

    # Derived content, populated only when mode_used is DIFF.
    # A clean, standard unified diff for tools, redirection, or scripting.
    unified_diff: str | None = None
    # The full conversational response, with diffs embedded, for rich terminal display.
    display_content: str | None = None

    token_usage: TokenUsage | None = None
    cost: float | None = None


class SessionData(BaseModel):
    model: str
    history_start_index: int = 0
    context_files: list[str] = []
    chat_history: list[ChatMessage] = []
    last_response: LastResponse | None = None


class AIPatch(BaseModel):
    llm_file_path: str
    search_content: str
    replace_content: str
