from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, model_validator


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

    # Derived content, populated only when mode_used is DIFF.
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

    @model_validator(mode="before")
    @classmethod
    def migrate_session_data(cls, data: Any) -> Any:
        # Pydantic v2 calls validators on dicts, models, etc.
        # We only want to operate on the raw dict from JSON.
        if not isinstance(data, dict):
            return data

        # Migrate chat_history
        if "chat_history" in data and data["chat_history"]:
            migrated_history = []
            for message in data["chat_history"]:
                # If we're instantiating with model objects, they are already valid.
                if isinstance(message, BaseModel):
                    migrated_history.append(message)
                    continue

                # from here on we assume message is a dict from JSON
                # If it's already a migrated dict (has a timestamp), skip it
                if "timestamp" in message:
                    migrated_history.append(message)
                    continue

                # Old format detected, upgrade it in-place
                migrated_message = message.copy()
                now_utc = datetime.now(timezone.utc).isoformat()

                if message.get("role") == "user":
                    migrated_message["timestamp"] = now_utc
                    # Clean up fields that no longer belong to user messages
                    migrated_message.pop("token_usage", None)
                    migrated_message.pop("cost", None)

                elif message.get("role") == "assistant":
                    migrated_message["timestamp"] = now_utc
                    # Add new fields with sensible defaults
                    migrated_message["model"] = data.get("model", "unknown")
                    migrated_message["duration_ms"] = -1

                migrated_history.append(migrated_message)
            data["chat_history"] = migrated_history

        # Migrate last_response
        last_resp = data.get("last_response")
        if last_resp and "timestamp" not in last_resp:
            # Old format detected, upgrade it in-place
            migrated_resp = last_resp.copy()
            migrated_resp["model"] = data.get("model", "unknown")
            migrated_resp["timestamp"] = datetime.now(timezone.utc).isoformat()
            migrated_resp["duration_ms"] = -1  # Sentinel for unknown duration
            data["last_response"] = migrated_resp

        return data


class AIPatch(BaseModel):
    llm_file_path: str
    search_content: str
    replace_content: str
