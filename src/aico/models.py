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
    raw_content: str
    mode_used: Mode
    processed_content: str
    token_usage: TokenUsage | None = None
    cost: float | None = None


class SessionData(BaseModel):
    model: str
    history_start_index: int = 0
    context_files: list[str] = []
    chat_history: list[ChatMessage] = []
    last_response: LastResponse | None = None
