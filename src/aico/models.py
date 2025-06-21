from dataclasses import dataclass
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


class UserChatMessage(BaseModel):
    role: Literal["user"]
    content: str
    mode: Mode
    timestamp: str


class AssistantChatMessage(BaseModel):
    role: Literal["assistant"]
    content: str
    mode: Mode
    timestamp: str
    model: str
    duration_ms: int
    token_usage: TokenUsage | None = None
    cost: float | None = None


ChatMessageHistoryItem = UserChatMessage | AssistantChatMessage


class LastResponse(BaseModel):
    # The verbatim, original response from the LLM. This is the source of truth.
    raw_content: str
    mode_used: Mode

    # Derived content, populated whenever diff blocks are found in the raw_content.
    # A clean, standard unified diff for tools, redirection, or scripting.
    unified_diff: str | None = None
    # The full conversational response, with diffs embedded, for rich terminal display.
    display_content: str | None = None

    model: str
    timestamp: str
    duration_ms: int
    token_usage: TokenUsage | None = None
    cost: float | None = None


class SessionData(BaseModel):
    model: str
    history_start_index: int = 0
    context_files: list[str] = []
    chat_history: list[ChatMessageHistoryItem] = []
    last_response: LastResponse | None = None


class TokenInfo(BaseModel):
    description: str
    tokens: int
    note: str | None = None
    cost: float | None = None


class TokenReport(BaseModel):
    model: str
    components: list[TokenInfo]
    total_tokens: int
    total_cost: float | None = None
    max_input_tokens: int | None = None
    remaining_tokens: int | None = None


class AIPatch(BaseModel):
    llm_file_path: str
    search_content: str
    replace_content: str


@dataclass
class ProcessedDiffBlock:
    llm_file_path: str
    unified_diff: str
