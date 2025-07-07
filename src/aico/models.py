from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, Protocol, TypedDict, runtime_checkable

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


@dataclass(slots=True, frozen=True)
class UserChatMessage:
    role: Literal["user"]
    content: str
    mode: Mode
    timestamp: str
    piped_content: str | None = None
    passthrough: bool = False
    is_excluded: bool = False


@dataclass(slots=True, frozen=True)
class DerivedContent:
    unified_diff: str | None
    display_content: str | None


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
    is_excluded: bool = False


type ChatMessageHistoryItem = UserChatMessage | AssistantChatMessage


@dataclass(slots=True)
class SessionData:
    model: str
    context_files: Annotated[list[str], Field(default_factory=list)]
    chat_history: Annotated[list[ChatMessageHistoryItem], Field(default_factory=list)]
    history_start_index: int = 0


@dataclass(slots=True)
class TokenInfo:
    description: str
    tokens: int
    note: str | None = None
    cost: float | None = None


@dataclass(slots=True, frozen=True)
class TokenReport:
    model: str
    components: list[TokenInfo]
    total_tokens: int
    total_cost: float | None = None
    max_input_tokens: int | None = None
    remaining_tokens: int | None = None


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


@runtime_checkable
class LiteLLMUsage(Protocol):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@runtime_checkable
class LiteLLMDelta(Protocol):
    content: str | None


@runtime_checkable
class LiteLLMStreamChoice(Protocol):
    delta: LiteLLMDelta


@runtime_checkable
class LiteLLMChoiceContainer(Protocol):
    choices: Sequence[LiteLLMStreamChoice]


type FileContents = Mapping[str, str]


@dataclass(slots=True, frozen=True)
class AddonInfo:
    name: str
    path: Path
    help_text: str
    source: Literal["project", "user"]
