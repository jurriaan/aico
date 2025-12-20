from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Literal, TypedDict

import msgspec
from msgspec import Struct, field


class Mode(str, Enum):
    CONVERSATION = "conversation"
    DIFF = "diff"
    RAW = "raw"


class SessionPointer(TypedDict):
    type: Literal["aico_session_pointer_v1"]
    path: str


class BasicUserChatMessage(Struct, frozen=True, tag="user", tag_field="role"):
    content: str

    @property
    def role(self) -> Literal["user"]:
        return "user"


class BasicAssistantChatMessage(Struct, frozen=True, tag="assistant", tag_field="role"):
    content: str

    @property
    def role(self) -> Literal["assistant"]:
        return "assistant"


type AlignmentMessage = BasicUserChatMessage | BasicAssistantChatMessage


class TokenUsage(Struct, frozen=True):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost: float | None = None


class DisplayItem(TypedDict):
    type: Literal["markdown", "text", "diff"]
    content: str


class DerivedContent(Struct, frozen=True):
    unified_diff: str | None = None
    display_content: list[DisplayItem] | None = None


class TokenInfo(Struct):
    description: str
    tokens: int
    cost: float | None = None


class ContextFilesResponse(TypedDict):
    context_files: list[str]


class UserChatMessage(Struct, frozen=True, tag="user", tag_field="role"):
    content: str
    mode: Mode
    timestamp: str
    piped_content: str | None = None
    passthrough: bool = False

    @property
    def role(self) -> Literal["user"]:
        return "user"


class AssistantChatMessage(Struct, frozen=True, tag="assistant", tag_field="role"):
    content: str
    mode: Mode
    timestamp: str
    model: str
    duration_ms: int
    derived: DerivedContent | None = None
    token_usage: TokenUsage | None = None
    cost: float | None = None

    @property
    def role(self) -> Literal["assistant"]:
        return "assistant"


type ChatMessageHistoryItem = UserChatMessage | AssistantChatMessage


class MessagePairIndices(Struct, frozen=True):
    user_index: int
    assistant_index: int


class SessionData(Struct):
    model: str
    context_files: list[str] = field(default_factory=list)
    chat_history: dict[int, ChatMessageHistoryItem] = field(default_factory=dict)
    history_start_pair: int = 0
    excluded_pairs: list[int] = field(default_factory=list)


class ContextFile(Struct, frozen=True):
    path: str
    content: str
    mtime: float


class AIPatch(Struct, frozen=True):
    llm_file_path: str
    search_content: str
    replace_content: str


class ProcessedDiffBlock(Struct, frozen=True):
    llm_file_path: str
    unified_diff: str


class ProcessedPatchResult(Struct, frozen=True):
    new_content: str
    diff_block: ProcessedDiffBlock


class PatchApplicationResult(Struct, frozen=True):
    """The result of applying all patches from an LLM response."""

    post_patch_contents: "FileContents"
    baseline_contents_for_diff: "FileContents"
    warnings: list["WarningMessage"]


class ResolvedFilePath(Struct, frozen=True):
    path: str | None
    warning: str | None
    fallback_content: str | None


class WarningMessage(Struct, frozen=True):
    text: str


class FileHeader(Struct, frozen=True):
    llm_file_path: str


class UnparsedBlock(Struct, frozen=True):
    text: str


type StreamYieldItem = str | FileHeader | ProcessedDiffBlock | WarningMessage | UnparsedBlock


class LLMChatMessage(TypedDict):
    role: Literal["user", "assistant", "system"]
    content: str


type FileContents = Mapping[str, str]
type MetadataFileContents = Mapping[str, ContextFile]


class ActiveContext(TypedDict):
    """
    Represents the fully resolved runtime state for the current command.
    This acts as a facade over SessionData, hiding legacy vs shared storage details.
    """

    model: str
    context_files: list[str]
    # The actual list of messages to be sent to the LLM (filters/slicing already applied)
    active_history: list[ChatMessageHistoryItem]


class AddonInfo(msgspec.Struct, frozen=True):
    name: str
    path: Path
    help_text: str
    source: Literal["project", "user", "bundled"]


class ModelInfo(msgspec.Struct, frozen=True):
    max_input_tokens: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None


class InteractionResult(Struct, frozen=True):
    content: str
    display_items: list[DisplayItem] | None
    token_usage: TokenUsage | None
    cost: float | None
    duration_ms: int
    unified_diff: str | None
