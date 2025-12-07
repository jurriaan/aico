from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass


class Mode(str, Enum):
    CONVERSATION = "conversation"
    DIFF = "diff"
    RAW = "raw"


class SessionPointer(TypedDict):
    type: Literal["aico_session_pointer_v1"]
    path: str


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


class ContextFilesResponse(TypedDict):
    context_files: list[str]


@pydantic_dataclass(slots=True, frozen=True)
class UserChatMessage:
    role: Literal["user"]
    content: str
    mode: Mode
    timestamp: str
    piped_content: str | None = None
    passthrough: bool = False


@pydantic_dataclass(slots=True, frozen=True)
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


type ChatMessageHistoryItem = UserChatMessage | AssistantChatMessage


@dataclass(slots=True, frozen=True)
class MessagePairIndices:
    user_index: int
    assistant_index: int


@pydantic_dataclass(slots=True)
class SessionData:
    model: str
    context_files: list[str] = Field(default_factory=list)
    chat_history: list[ChatMessageHistoryItem] = Field(default_factory=list)
    history_start_pair: int = 0
    excluded_pairs: list[int] = Field(default_factory=list)
    # In-memory signal that chat_history is a pre-sliced active window (shared-history).
    is_pre_sliced: Annotated[bool, Field(exclude=True)] = False


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


class ActiveContext(TypedDict):
    """
    Represents the fully resolved runtime state for the current command.
    This acts as a facade over SessionData, hiding legacy vs shared storage details.
    """

    model: str
    context_files: list[str]
    # The actual list of messages to be sent to the LLM (filters/slicing already applied)
    active_history: list[ChatMessageHistoryItem]


@dataclass(slots=True, frozen=True)
class AddonInfo:
    name: str
    path: Path
    help_text: str
    source: Literal["project", "user", "bundled"]


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
