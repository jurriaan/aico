from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import Field
from pydantic.dataclasses import dataclass


class Mode(str, Enum):
    CONVERSATION = "conversation"
    DIFF = "diff"
    RAW = "raw"


@dataclass(slots=True, frozen=True)
class BasicUserChatMessage:
    content: str
    role: Literal["user"] = "user"


@dataclass(slots=True, frozen=True)
class BasicAssistantChatMessage:
    content: str
    role: Literal["assistant"] = "assistant"


type AlignmentMessage = BasicUserChatMessage | BasicAssistantChatMessage


@dataclass(slots=True, frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost: float | None = None


class DisplayItem(TypedDict):
    type: Literal["markdown", "text", "diff"]
    content: str


@dataclass(slots=True, frozen=True)
class DerivedContent:
    unified_diff: str | None = None
    display_content: list[DisplayItem] | str | None = None


@dataclass(slots=True)
class TokenInfo:
    description: str
    tokens: int
    cost: float | None = None


@dataclass(slots=True, frozen=True)
class ContextFilesResponse:
    context_files: list[str]


@dataclass(slots=True, frozen=True)
class UserChatMessage:
    role: Literal["user"]
    content: str
    mode: Mode
    timestamp: str
    piped_content: str | None = None
    passthrough: bool = False
    is_excluded: bool = Field(default=False, exclude=True)  # Legacy flag; kept for in-memory compatibility


@dataclass(slots=True, frozen=True)
class AssistantChatMessage:
    role: Literal["assistant"]
    content: str
    mode: Mode
    timestamp: str
    model: str
    duration_ms: int
    derived: DerivedContent | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None
    is_excluded: bool = Field(default=False, exclude=True)  # Legacy flag; kept for in-memory compatibility


type ChatMessageHistoryItem = UserChatMessage | AssistantChatMessage


@dataclass(slots=True, frozen=True)
class MessagePairIndices:
    user_index: int
    assistant_index: int


@dataclass(slots=True)
class SessionData:
    model: str
    context_files: list[str] = Field(default_factory=list)
    chat_history: list[ChatMessageHistoryItem] = Field(default_factory=list)
    history_start_pair: int = 0
    excluded_pairs: list[int] = Field(default_factory=list)
    # Legacy, message-centric history start index; kept for backward compatibility and migration.
    history_start_index: int | None = Field(default=None, exclude=True)
    # Total number of pairs in the full history (used for shared-history metadata and error messages).
    total_pairs_in_history: int | None = Field(default=None, exclude=True)
    # In-memory signal that chat_history is a pre-sliced active window (shared-history).
    is_pre_sliced: bool = Field(default=False, exclude=True)


@dataclass(slots=True, frozen=True)
class AIPatch:
    llm_file_path: str
    search_content: str
    replace_content: str


@dataclass(slots=True, frozen=True)
class ProcessedDiffBlock:
    llm_file_path: str
    unified_diff: str


@dataclass(slots=True, frozen=True)
class ProcessedPatchResult:
    new_content: str
    diff_block: ProcessedDiffBlock


@dataclass(slots=True, frozen=True)
class PatchApplicationResult:
    """The result of applying all patches from an LLM response."""

    post_patch_contents: "FileContents"
    baseline_contents_for_diff: "FileContents"
    warnings: list["WarningMessage"]


@dataclass(slots=True, frozen=True)
class ResolvedFilePath:
    path: str | None
    warning: str | None
    fallback_content: str | None


@dataclass(slots=True, frozen=True)
class WarningMessage:
    text: str


@dataclass(slots=True, frozen=True)
class FileHeader:
    llm_file_path: str


@dataclass(slots=True, frozen=True)
class UnparsedBlock:
    text: str


type StreamYieldItem = str | FileHeader | ProcessedDiffBlock | WarningMessage | UnparsedBlock


class LLMChatMessage(TypedDict):
    role: Literal["user", "assistant", "system"]
    content: str


type FileContents = Mapping[str, str]


@dataclass(slots=True, frozen=True)
class AddonInfo:
    name: str
    path: Path
    help_text: str
    source: Literal["project", "user"]


@dataclass(slots=True, frozen=True)
class ModelInfo:
    max_input_tokens: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None


@dataclass(slots=True, frozen=True)
class InteractionResult:
    content: str
    display_items: list[DisplayItem] | None
    token_usage: TokenUsage | None
    cost: float | None
    duration_ms: int
    unified_diff: str | None
