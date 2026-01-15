use crate::consts::SESSION_FILE_NAME;
use crate::exceptions::AicoError;
use crate::fs::atomic_write_json;
use crate::historystore::store::HistoryStore;
use crate::models::ActiveWindowSummary;
use crate::models::{HistoryRecord, SessionPointer, SessionView};
use crossterm::style::Stylize;
use std::env;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

#[derive(Debug)]
pub struct Session {
    pub file_path: PathBuf,
    pub root: PathBuf,
    pub view_path: PathBuf,
    pub view: SessionView,
    pub store: HistoryStore,
    pub context_content: std::collections::HashMap<String, String>,
    pub history: std::collections::HashMap<usize, crate::models::MessageWithContext>,
}

impl Session {
    /// Loads the session from the environment or current working directory.
    pub fn load_active() -> Result<Self, AicoError> {
        if let Ok(env_path) = env::var("AICO_SESSION_FILE") {
            let path = PathBuf::from(env_path);
            if !path.is_absolute() {
                return Err(AicoError::Session(
                    "AICO_SESSION_FILE must be an absolute path".into(),
                ));
            }
            if !path.exists() {
                return Err(AicoError::Session(
                    "Session file specified in AICO_SESSION_FILE does not exist".into(),
                ));
            }
            return Self::load(path);
        }

        let session_file = find_session_file().ok_or_else(|| {
            AicoError::Session(format!("No session file '{}' found.", SESSION_FILE_NAME))
        })?;

        Self::load(session_file)
    }

    /// Loads a session from a specific pointer file path.
    pub fn load(session_file: PathBuf) -> Result<Self, AicoError> {
        let root = session_file
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .to_path_buf();

        let pointer_json = std::fs::read_to_string(&session_file)?;

        if pointer_json.trim().is_empty() {
            return Err(AicoError::SessionIntegrity(format!(
                "Session file '{}' is empty.",
                SESSION_FILE_NAME
            )));
        }

        if !pointer_json.contains("aico_session_pointer_v1") {
            return Err(AicoError::SessionIntegrity(format!(
                "Detected a legacy session file at {}.\n\
                This version of aico only supports the Shared History format.\n\
                Please run 'aico migrate-shared-history' (using the Python version) to upgrade your project.",
                session_file.display()
            )));
        }

        let pointer: SessionPointer = serde_json::from_str(&pointer_json)
            .map_err(|_| AicoError::SessionIntegrity("Invalid pointer file format".into()))?;

        // Resolve View Path (relative to pointer file)
        let view_path = root.join(&pointer.path);
        if !view_path.exists() {
            return Err(AicoError::Session(format!(
                "Missing view file: {}",
                view_path.display()
            )));
        }

        let view_json = std::fs::read_to_string(&view_path)?;
        let view: SessionView = serde_json::from_str(&view_json)?;

        let history_root = root.join(".aico").join("history");
        let store = HistoryStore::new(history_root);

        // --- Eager Loading ---
        let context_content: std::collections::HashMap<String, String> = view
            .context_files
            .iter()
            .filter_map(|rel_path| {
                let abs_path = root.join(rel_path);
                std::fs::read_to_string(&abs_path)
                    .ok()
                    .map(|content| (rel_path.clone(), content))
            })
            .collect();

        let history = std::collections::HashMap::new();

        Ok(Self {
            file_path: session_file,
            root,
            view_path,
            view,
            store,
            context_content,
            history,
        })
    }

    pub fn save_view(&self) -> Result<(), AicoError> {
        crate::fs::atomic_write_json(&self.view_path, &self.view)
    }

    pub fn sessions_dir(&self) -> PathBuf {
        self.root.join(".aico").join("sessions")
    }

    pub fn get_view_path(&self, name: &str) -> PathBuf {
        self.sessions_dir().join(format!("{}.json", name))
    }

    pub fn switch_to_view(&self, new_view_path: &Path) -> Result<(), AicoError> {
        // Calculate relative path for the pointer
        // simple approach: .aico/sessions/<name>.json
        let file_name = new_view_path
            .file_name()
            .ok_or_else(|| AicoError::Session("Invalid view path".into()))?;

        let rel_path = Path::new(".aico").join("sessions").join(file_name);

        let pointer = SessionPointer {
            pointer_type: "aico_session_pointer_v1".to_string(),
            path: rel_path.to_string_lossy().replace('\\', "/"),
        };

        atomic_write_json(&self.file_path, &pointer)?;

        Ok(())
    }

    pub fn num_pairs(&self) -> usize {
        self.view.message_indices.len() / 2
    }

    pub fn resolve_pair_index(&self, index_str: &str) -> Result<usize, AicoError> {
        self.resolve_pair_index_internal(index_str, false)
    }

    pub fn resolve_indices(&self, indices: &[String]) -> Result<Vec<usize>, AicoError> {
        let num_pairs = self.num_pairs();
        let mut result = Vec::new();
        // Default to last if empty
        if indices.is_empty() {
            if num_pairs == 0 {
                return Err(AicoError::InvalidInput(
                    "No message pairs found in history.".into(),
                ));
            }
            result.push(num_pairs - 1);
            return Ok(result);
        }

        for arg in indices {
            // Handle ranges "0..2"
            if let Some((start_str, end_str)) = arg.split_once("..") {
                let is_start_neg = start_str.starts_with('-');
                let is_end_neg = end_str.starts_with('-');

                if is_start_neg != is_end_neg {
                    return Err(AicoError::InvalidInput(format!(
                        "Invalid index '{}'. Mixed positive and negative indices in a range are not supported.",
                        arg
                    )));
                }

                let start_idx = self.resolve_pair_index_internal(start_str, false)? as isize;
                let end_idx = self.resolve_pair_index_internal(end_str, false)? as isize;

                let step = if start_idx <= end_idx { 1 } else { -1 };
                let len = (start_idx - end_idx).unsigned_abs() + 1;

                result.extend(
                    std::iter::successors(Some(start_idx), move |&n| Some(n + step))
                        .take(len)
                        .map(|i| i as usize),
                );
            } else {
                result.push(self.resolve_pair_index_internal(arg, false)?);
            }
        }
        result.sort();
        result.dedup();
        Ok(result)
    }

    pub fn resolve_pair_index_internal(
        &self,
        index_str: &str,
        allow_past_end: bool,
    ) -> Result<usize, AicoError> {
        let num_pairs = self.num_pairs();
        if num_pairs == 0 {
            return Err(AicoError::InvalidInput(
                "No message pairs found in history.".into(),
            ));
        }

        let index = index_str.parse::<isize>().map_err(|_| {
            AicoError::InvalidInput(format!(
                "Invalid index '{}'. Must be an integer.",
                index_str
            ))
        })?;

        let resolved = if index < 0 {
            (num_pairs as isize) + index
        } else {
            index
        };

        let max = if allow_past_end {
            num_pairs
        } else {
            if num_pairs == 0 {
                return Err(AicoError::InvalidInput(
                    "No message pairs found in history.".into(),
                ));
            }
            num_pairs - 1
        };

        if resolved < 0 || resolved > max as isize {
            let range = if num_pairs == 1 && !allow_past_end {
                "Valid indices are in the range 0 (or -1).".to_string()
            } else {
                let mut base = format!(
                    "Valid indices are in the range 0 to {} (or -1 to -{})",
                    num_pairs - 1,
                    num_pairs
                );

                if allow_past_end {
                    base.push_str(&format!(" (or {} to clear context)", num_pairs));
                }
                base
            };

            return Err(AicoError::InvalidInput(format!(
                "Index out of bounds. {}",
                range
            )));
        }

        Ok(resolved as usize)
    }

    pub fn edit_message(
        &mut self,
        message_index: usize,
        new_content: String,
    ) -> Result<(), AicoError> {
        if message_index >= self.view.message_indices.len() {
            return Err(AicoError::Session("Message index out of bounds".into()));
        }

        let original_global_idx = self.view.message_indices[message_index];
        let original_records = self.store.read_many(&[original_global_idx])?;
        let original_record = original_records
            .first()
            .ok_or_else(|| AicoError::SessionIntegrity("Record not found".into()))?;

        let mut new_record = original_record.clone();
        new_record.content = new_content;
        new_record.edit_of = Some(original_global_idx);
        // We preserve the original timestamp to keep the context horizon stable.
        new_record.timestamp = original_record.timestamp;

        // Recompute derived content if it's an assistant message
        if new_record.role == crate::models::Role::Assistant {
            new_record.derived = self.compute_derived_content(&new_record.content);
        } else {
            new_record.derived = None;
        }

        let new_global_idx = self.store.append(&new_record)?;
        self.view.message_indices[message_index] = new_global_idx;

        // Synchronize in-memory history map for this specific message
        if let Some(msg) = self.history.get_mut(&original_global_idx) {
            msg.record = new_record.clone();
            msg.global_index = new_global_idx;
        }
        self.history.insert(
            new_global_idx,
            crate::models::MessageWithContext {
                record: new_record,
                global_index: new_global_idx,
                pair_index: message_index / 2,
                is_excluded: self.view.excluded_pairs.contains(&(message_index / 2)),
            },
        );

        self.save_view()?;
        Ok(())
    }

    pub fn compute_derived_content(&self, content: &str) -> Option<crate::models::DerivedContent> {
        use crate::diffing::parser::StreamParser;

        let mut parser = StreamParser::new(&self.context_content);
        // Ensure content ends with a newline to trigger complete parsing of the final block
        let gated_content = if content.ends_with('\n') {
            content.to_string()
        } else {
            format!("{}\n", content)
        };
        parser.feed(&gated_content);

        let (diff, display_items, _warnings) = parser.final_resolve(&self.root);

        // Only create derived content if there is a meaningful diff, or if the structured
        // display items are different from the raw content.
        let has_structural_diversity = !diff.is_empty()
            || display_items.iter().any(|item| match item {
                crate::models::DisplayItem::Markdown(m) => m.trim() != content.trim(),
                _ => true,
            });

        if has_structural_diversity {
            Some(crate::models::DerivedContent {
                unified_diff: if diff.is_empty() { None } else { Some(diff) },
                display_content: Some(display_items),
            })
        } else {
            None
        }
    }

    pub fn summarize_active_window(
        &self,
        history_vec: &[crate::models::MessageWithContext],
    ) -> Result<Option<ActiveWindowSummary>, AicoError> {
        if history_vec.is_empty() {
            return Ok(None);
        }

        let mut total_pairs = 0;
        let mut excluded_in_window = 0;
        let mut has_dangling = false;

        let mut i = 0;
        while i < history_vec.len() {
            let current = &history_vec[i];
            if current.record.role == crate::models::Role::User
                && let Some(next) = history_vec.get(i + 1)
                && next.record.role == crate::models::Role::Assistant
                && next.pair_index == current.pair_index
            {
                total_pairs += 1;
                if current.is_excluded {
                    excluded_in_window += 1;
                }
                i += 2;
            } else {
                has_dangling = true;
                i += 1;
            }
        }

        Ok(Some(ActiveWindowSummary {
            active_pairs: total_pairs,
            active_start_id: self.view.history_start_pair,
            active_end_id: self.view.message_indices.len().saturating_sub(1) / 2,
            excluded_in_window,
            pairs_sent: total_pairs.saturating_sub(excluded_in_window),
            has_dangling,
        }))
    }

    pub fn get_context_files(&self) -> Vec<String> {
        self.view.context_files.clone()
    }

    pub fn warn_missing_files(&self) {
        // Collect references (&String) instead of cloning
        let mut missing: Vec<&String> = self
            .view
            .context_files
            .iter()
            .filter(|f| !self.context_content.contains_key(*f))
            .collect();

        if !missing.is_empty() {
            missing.sort();
            let joined = missing
                .iter()
                .map(|s| s.as_str())
                .collect::<Vec<_>>()
                .join(" ");

            eprintln!(
                "{}",
                format!("Warning: Context files not found on disk: {}", joined).yellow()
            );
        }
    }

    pub fn fetch_pair(
        &self,
        index: usize,
    ) -> Result<(HistoryRecord, HistoryRecord, usize, usize), AicoError> {
        let u_abs = index * 2;
        let a_abs = u_abs + 1;

        if a_abs >= self.view.message_indices.len() {
            return Err(AicoError::InvalidInput(format!(
                "Pair index {} is out of bounds.",
                index
            )));
        }

        let u_global = self.view.message_indices[u_abs];
        let a_global = self.view.message_indices[a_abs];

        // 1. Memory Strategy: Use HashMap for O(1) lookup
        if let (Some(u_msg), Some(a_msg)) =
            (self.history.get(&u_global), self.history.get(&a_global))
        {
            return Ok((
                u_msg.record.clone(),
                a_msg.record.clone(),
                u_global,
                a_global,
            ));
        }

        // 2. Fallback Strategy: Hit the store surgically
        let records = self.store.read_many(&[u_global, a_global])?;
        if records.len() != 2 {
            return Err(AicoError::SessionIntegrity(
                "Failed to fetch full pair from store".into(),
            ));
        }

        Ok((records[0].clone(), records[1].clone(), u_global, a_global))
    }

    pub fn append_record_to_view(&mut self, record: HistoryRecord) -> Result<(), AicoError> {
        let pair_index = self.view.message_indices.len() / 2;
        let global_idx = self.store.append(&record)?;
        self.view.message_indices.push(global_idx);

        // Update in-memory map lazily
        self.history.insert(
            global_idx,
            crate::models::MessageWithContext {
                record,
                global_index: global_idx,
                pair_index,
                is_excluded: self.view.excluded_pairs.contains(&pair_index),
            },
        );

        Ok(())
    }

    pub fn append_pair(
        &mut self,
        user_record: HistoryRecord,
        assistant_record: HistoryRecord,
    ) -> Result<(), AicoError> {
        self.append_record_to_view(user_record)?;
        self.append_record_to_view(assistant_record)?;
        self.save_view()
    }

    pub fn resolve_context_state(
        &self,
        history: &[crate::models::MessageWithContext],
    ) -> Result<crate::models::ContextState<'_>, AicoError> {
        let horizon = history
            .first()
            .map(|m| m.record.timestamp)
            .unwrap_or_else(|| {
                "3000-01-01T00:00:00Z"
                    .parse::<chrono::DateTime<chrono::Utc>>()
                    .unwrap()
            });

        let mut static_files = vec![];
        let mut floating_files = vec![];
        let mut latest_floating_mtime = chrono::DateTime::<chrono::Utc>::MIN_UTC;

        for (rel_path, content) in &self.context_content {
            let abs_path = self.root.join(rel_path);
            if let Ok(meta) = std::fs::metadata(&abs_path) {
                // Parity with math.ceil(mtime) from Python
                let duration = meta
                    .modified()
                    .map_err(|e| AicoError::Session(e.to_string()))?
                    .duration_since(UNIX_EPOCH)
                    .map_err(|e| AicoError::Session(e.to_string()))?;

                let mtime_secs = duration.as_secs_f64().ceil() as i64;
                let mtime = chrono::TimeZone::timestamp_opt(&chrono::Utc, mtime_secs, 0).unwrap();

                if mtime < horizon {
                    static_files.push((rel_path.as_str(), content.as_str()));
                } else {
                    if mtime > latest_floating_mtime {
                        latest_floating_mtime = mtime;
                    }
                    floating_files.push((rel_path.as_str(), content.as_str()));
                }
            }
        }

        // Determine Splice Point
        let splice_idx = if floating_files.is_empty() {
            history.len()
        } else {
            history
                .iter()
                .position(|item| item.record.timestamp > latest_floating_mtime)
                .unwrap_or(history.len())
        };

        Ok(crate::models::ContextState {
            static_files,
            floating_files,
            splice_idx,
        })
    }
}

pub fn find_session_file() -> Option<PathBuf> {
    let mut current = env::current_dir().ok()?;
    loop {
        let check = current.join(SESSION_FILE_NAME);
        if check.is_file() {
            return Some(check);
        }
        if !current.pop() {
            break;
        }
    }
    None
}
