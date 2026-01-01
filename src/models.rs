use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

// --- Enums ---

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    Conversation,
    Diff,
    Raw,
}

impl std::fmt::Display for Mode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Mode::Conversation => write!(f, "conversation"),
            Mode::Diff => write!(f, "diff"),
            Mode::Raw => write!(f, "raw"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    User,
    Assistant,
    System,
}

impl std::fmt::Display for Role {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Role::User => write!(f, "user"),
            Role::Assistant => write!(f, "assistant"),
            Role::System => write!(f, "system"),
        }
    }
}

// --- Shared History Models (historystore/models.py) ---

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HistoryRecord {
    pub role: Role,
    pub content: String,
    pub mode: Mode,
    #[serde(default = "default_timestamp")]
    pub timestamp: DateTime<Utc>,

    #[serde(default)]
    pub passthrough: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub piped_content: Option<String>,

    // Assistant-only optional metadata
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub token_usage: Option<TokenUsage>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub derived: Option<DerivedContent>,

    // Edit lineage
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub edit_of: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SessionView {
    pub model: String,
    #[serde(default)]
    pub context_files: Vec<String>,
    #[serde(default)]
    pub message_indices: Vec<usize>,
    #[serde(default)]
    pub history_start_pair: usize,
    #[serde(default)]
    pub excluded_pairs: Vec<usize>,
    #[serde(default = "default_timestamp")]
    pub created_at: DateTime<Utc>,
}

// --- Session Pointer (.ai_session.json) ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionPointer {
    #[serde(rename = "type")]
    pub pointer_type: String, // "aico_session_pointer_v1"
    pub path: String,
}

// --- Supporting Structs ---

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TokenUsage {
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_tokens: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cached_tokens: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_tokens: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DerivedContent {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unified_diff: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub display_content: Option<Vec<DisplayItem>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", content = "content", rename_all = "lowercase")]
pub enum DisplayItem {
    #[serde(alias = "text")]
    Markdown(String),
    Diff(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextFile {
    pub path: String,
    pub content: String,
    pub mtime: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessageWithId {
    #[serde(flatten)]
    pub record: HistoryRecord,
    pub id: usize,
}

#[derive(Debug, Clone)]
pub struct MessageWithContext {
    pub record: HistoryRecord,
    pub global_index: usize,
    pub pair_index: usize,
    pub is_excluded: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessagePairJson {
    pub pair_index: usize,
    pub user: MessageWithId,
    pub assistant: MessageWithId,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum AddonSource {
    Project,
    User,
    Bundled,
}

impl std::fmt::Display for AddonSource {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AddonSource::Project => write!(f, "project"),
            AddonSource::User => write!(f, "user"),
            AddonSource::Bundled => write!(f, "bundled"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct AddonInfo {
    pub name: String,
    pub path: std::path::PathBuf,
    pub help_text: String,
    pub source: AddonSource,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenInfo {
    pub description: String,
    pub tokens: u32,
    pub cost: Option<f64>,
}

pub struct ActiveWindowSummary {
    pub active_pairs: usize,
    pub active_start_id: usize,
    pub active_end_id: usize,
    pub excluded_in_window: usize,
    pub pairs_sent: usize,
    pub has_dangling: bool,
}

// --- Diffing / Streaming Models ---

#[derive(Debug, Clone, PartialEq)]
pub struct AIPatch {
    pub llm_file_path: String,
    pub search_content: String,
    pub replace_content: String,
    pub indent: String,
    pub raw_block: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProcessedDiffBlock {
    pub llm_file_path: String,
    pub unified_diff: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FileHeader {
    pub llm_file_path: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WarningMessage {
    pub text: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct UnparsedBlock {
    pub text: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum StreamYieldItem {
    Text(String),
    IncompleteBlock(String),
    FileHeader(FileHeader),
    DiffBlock(ProcessedDiffBlock),
    Patch(AIPatch),
    Warning(WarningMessage),
    Unparsed(UnparsedBlock),
}

impl StreamYieldItem {
    pub fn is_warning(&self) -> bool {
        matches!(self, StreamYieldItem::Warning(_))
    }

    pub fn to_display_item(self, is_final: bool) -> Option<DisplayItem> {
        match self {
            StreamYieldItem::Text(t) => Some(DisplayItem::Markdown(t)),
            StreamYieldItem::FileHeader(h) => Some(DisplayItem::Markdown(format!(
                "File: `{}`\n",
                h.llm_file_path
            ))),
            StreamYieldItem::DiffBlock(db) => Some(DisplayItem::Diff(db.unified_diff)),
            StreamYieldItem::Warning(w) => {
                Some(DisplayItem::Markdown(format!("[!WARNING]\n{}\n\n", w.text)))
            }
            StreamYieldItem::Unparsed(u) => Some(DisplayItem::Markdown(format!(
                "\n`````text\n{}\n`````\n",
                u.text
            ))),
            StreamYieldItem::IncompleteBlock(t) => {
                if is_final {
                    Some(DisplayItem::Markdown(t))
                } else {
                    None
                }
            }
            StreamYieldItem::Patch(_) => None,
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct StatusResponse {
    pub session_name: String,
    pub model: String,
    pub context_files: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_tokens: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_cost: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InteractionResult {
    pub content: String,
    pub display_items: Option<Vec<DisplayItem>>,
    pub token_usage: Option<TokenUsage>,
    pub cost: Option<f64>,
    pub duration_ms: u64,
    pub unified_diff: Option<String>,
}

#[derive(Debug, Clone)]
pub struct InteractionConfig {
    pub mode: Mode,
    pub no_history: bool,
    pub passthrough: bool,
    pub model_override: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ContextState {
    pub static_files: Vec<(String, String)>,
    pub floating_files: Vec<(String, String)>,
    pub splice_idx: usize,
}

// --- Helpers ---

pub fn format_file_context_xml(path: &str, content: &str) -> String {
    let mut block = format!("  <file path=\"{}\">\n", path);
    block.push_str(content);
    if !content.ends_with('\n') {
        block.push('\n');
    }
    block.push_str("  </file>\n");
    block
}

pub fn default_timestamp() -> DateTime<Utc> {
    Utc::now()
}
