from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Mode(str, Enum):
    RAW = "raw"
    DIFF = "diff"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    mode: Mode


class LastResponse(BaseModel):
    raw_content: str
    mode_used: Mode
    processed_content: str


class SessionData(BaseModel):
    context_files: list[str] = []
    chat_history: list[ChatMessage] = []
    last_response: LastResponse | None = None
