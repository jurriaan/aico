use crate::diffing::diff_utils::generate_diff;
use crate::diffing::patching::create_patched_content;
use crate::models::{StreamYieldItem, UnparsedBlock};
use regex::Regex;
use std::collections::HashMap;
use std::path::Path;

pub struct StreamParser<'a> {
    buffer: String,
    current_file: Option<String>,
    /// Queue for items found during parsing that are waiting to be yielded.
    yield_queue: std::collections::VecDeque<StreamYieldItem>,
    /// Baseline contents provided by the session.
    baseline: &'a HashMap<String, String>,
    /// Overlay of files modified during this stream.
    overlay: HashMap<String, String>,
    /// Maps filenames to their content pre-modification in this stream.
    discovered_baseline: HashMap<String, String>,
}

impl<'a> StreamParser<'a> {
    pub fn get_pending_content(&self) -> String {
        self.buffer.clone()
    }

    pub fn new(original_contents: &'a HashMap<String, String>) -> Self {
        Self {
            buffer: String::new(),
            current_file: None,
            yield_queue: std::collections::VecDeque::new(),
            baseline: original_contents,
            overlay: HashMap::new(),
            discovered_baseline: HashMap::new(),
        }
    }

    /// Feeds a new chunk of text into the parser.
    /// Use the Iterator implementation (next()) to retrieve yielded items.
    pub fn feed(&mut self, chunk: &str) {
        self.buffer.push_str(chunk);
    }

    /// Convenience method to feed content and return resolved yields in one go.
    pub fn parse_and_resolve(&mut self, chunk: &str, session_root: &Path) -> Vec<StreamYieldItem> {
        self.feed(chunk);
        let raw_yields: Vec<_> = self.by_ref().collect();
        self.process_yields(raw_yields, session_root)
    }

    /// Centralized finalization logic to resolve any remaining buffer content,
    /// process patches, and build the final diff and structured display items.
    pub fn final_resolve(
        &mut self,
        session_root: &Path,
    ) -> (String, Vec<crate::models::DisplayItem>, Vec<String>) {
        // 1. Drain any items currently in the iterator/buffer
        let (_, raw_yields, _) = self.finish("");

        // 2. Resolve Patch items into DiffBlocks (and update overlay/discovered_baseline)
        let processed = self.process_yields(raw_yields, session_root);

        // 3. Collect final state
        let warnings = self.collect_warnings(&processed);
        let diff = self.build_final_unified_diff();
        let display_items = processed
            .into_iter()
            .filter_map(|y| y.to_display_item(true))
            .collect();

        (diff, display_items, warnings)
    }
}

impl<'a> Iterator for StreamParser<'a> {
    type Item = StreamYieldItem;

    fn next(&mut self) -> Option<Self::Item> {
        static FILE_HEADER_RE: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
        let file_header_re = FILE_HEADER_RE.get_or_init(|| {
            Regex::new(r"(?m)^(?P<line>[ \t]*File:[ \t]*(?P<path>.*?)\r?\n)").unwrap()
        });

        loop {
            // 1. First, drain the pre-parsed queue
            if let Some(item) = self.yield_queue.pop_front() {
                return Some(item);
            }

            if self.buffer.is_empty() {
                return None;
            }

            // 2. If we are currently "inside" a file's content section
            if let Some(llm_file_path) = self.current_file.clone() {
                let next_header_idx = file_header_re
                    .find(&self.buffer)
                    .map(|m| m.start())
                    .unwrap_or(self.buffer.len());

                if next_header_idx > 0 {
                    let (chunk_items, consumed_bytes) =
                        self.process_file_chunk(&llm_file_path, &self.buffer[..next_header_idx]);
                    self.buffer.drain(..consumed_bytes);

                    if !chunk_items.is_empty() {
                        self.yield_queue.extend(chunk_items);
                        continue;
                    }

                    if consumed_bytes > 0 {
                        continue;
                    }

                    // If waiting for data within a file block, do not fall through to Text parsing.
                    if next_header_idx == self.buffer.len() {
                        return None;
                    }
                }

                if next_header_idx < self.buffer.len() {
                    self.current_file = None;
                    continue;
                }
            }

            // 3. Look for Global File Headers
            if let Some(caps) = file_header_re.captures(&self.buffer) {
                let mat = caps.get(0).unwrap();
                if mat.start() > 0 {
                    let text = self.buffer[..mat.start()].to_string();
                    self.buffer.drain(..mat.start());
                    return Some(StreamYieldItem::Text(text));
                }

                let path_str = caps
                    .name("path")
                    .unwrap()
                    .as_str()
                    .trim()
                    .trim_matches(|c| c == '*' || c == '`')
                    .to_string();
                self.current_file = Some(path_str.clone());
                self.buffer.drain(..mat.end());
                return Some(StreamYieldItem::FileHeader(crate::models::FileHeader {
                    llm_file_path: path_str,
                }));
            }

            // 4. Handle remaining buffer as Markdown Text
            let text = &self.buffer;
            let mut stable_len = text.len();

            if self.is_incomplete(text) {
                if let Some(m) = file_header_re.find(text) {
                    stable_len = m.start();
                } else if let Some(search_idx) = text.find("<<<<<<< SEARCH") {
                    stable_len = text[..search_idx].rfind('\n').map(|i| i + 1).unwrap_or(0);
                } else if let Some(last_newline) = text.rfind('\n') {
                    let last_line = &text[last_newline + 1..];
                    if self.is_incomplete(last_line) {
                        stable_len = last_newline + 1;
                    }
                } else {
                    stable_len = 0;
                }
            }

            if stable_len > 0 {
                let text_yield = self.buffer[..stable_len].to_string();
                self.buffer.drain(..stable_len);
                return Some(StreamYieldItem::Text(text_yield));
            }

            return None;
        }
    }
}

impl<'a> StreamParser<'a> {
    fn is_incomplete(&self, text: &str) -> bool {
        // Check if we are inside an unclosed SEARCH block
        if let Some(idx) = text.find("<<<<<<< SEARCH") {
            let line_start = text[..idx].rfind('\n').map(|i| i + 1).unwrap_or(0);
            let indent = &text[line_start..idx];
            if indent.chars().all(|c| c.is_whitespace()) && !text.contains(">>>>>>> REPLACE") {
                return true;
            }
        }

        // Check for partial tokens at the end of the buffer
        if let Some(last_line) = text.split('\n').next_back() {
            let trimmed = last_line.trim_start();
            if !trimmed.is_empty() {
                // Partial "File:" header?
                // Note: We deliberately don't check for \r here, forcing a wait for \n
                if "File:".starts_with(trimmed) && trimmed.len() < "File:".len() {
                    return true;
                }
                if trimmed.starts_with("File:") && !text.ends_with('\n') {
                    return true;
                }

                // Partial markers?
                for marker in ["<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"] {
                    if marker.starts_with(trimmed) && marker.len() > trimmed.len() {
                        return true;
                    }
                }
            }
        }
        false
    }

    fn process_file_chunk(&self, llm_path: &str, chunk: &str) -> (Vec<StreamYieldItem>, usize) {
        let mut items = Vec::new();
        let mut cursor = 0;
        let search_pattern = "<<<<<<< SEARCH";
        let sep_pattern = "=======";
        let replace_pattern = ">>>>>>> REPLACE";

        while cursor < chunk.len() {
            let search_idx = match chunk[cursor..].find(search_pattern) {
                Some(i) => cursor + i,
                None => break,
            };

            // Capture indentation from the start of the line up to the marker
            let line_start = chunk[..search_idx].rfind('\n').map(|i| i + 1).unwrap_or(0);
            let indent = chunk[line_start..search_idx].to_string();

            // Verify indent consists only of whitespace
            if !indent.chars().all(|c| c.is_whitespace()) {
                // If it's not a marker at the start of a line, skip it
                items.push(StreamYieldItem::Text(
                    chunk[cursor..search_idx + 1].to_string(),
                ));
                cursor = search_idx + 1;
                continue;
            }

            let block_search_start = search_idx + search_pattern.len();
            let block_search_start_content =
                block_search_start + consume_line_ending(&chunk[block_search_start..]);

            let (sep_line_start, sep_line_end) =
                match find_marker_with_indent(chunk, sep_pattern, block_search_start, &indent) {
                    Some(pair) => pair,
                    None => {
                        if search_idx > cursor {
                            items
                                .push(StreamYieldItem::Text(chunk[cursor..search_idx].to_string()));
                        }
                        return (items, search_idx);
                    }
                };

            let block_replace_start_content =
                sep_line_end + consume_line_ending(&chunk[sep_line_end..]);

            let (replace_line_start, _replace_line_end) =
                match find_marker_with_indent(chunk, replace_pattern, sep_line_end, &indent) {
                    Some(pair) => pair,
                    None => {
                        if search_idx > cursor {
                            items
                                .push(StreamYieldItem::Text(chunk[cursor..search_idx].to_string()));
                        }
                        return (items, search_idx);
                    }
                };

            if search_idx > cursor {
                items.push(StreamYieldItem::Text(chunk[cursor..search_idx].to_string()));
            }

            let final_end = replace_line_start + indent.len() + replace_pattern.len();

            let search_content = &chunk[block_search_start_content..sep_line_start];
            let replace_content = &chunk[block_replace_start_content..replace_line_start];

            items.push(StreamYieldItem::Patch(crate::models::AIPatch {
                llm_file_path: llm_path.to_string(),
                search_content: search_content.to_string(),
                replace_content: replace_content.to_string(),
                indent: indent.clone(),
                raw_block: chunk[search_idx..final_end].to_string(),
            }));

            cursor = final_end;
        }

        if cursor < chunk.len() {
            let tail = &chunk[cursor..];
            if !self.is_incomplete(tail) {
                items.push(StreamYieldItem::Text(tail.to_string()));
                cursor = chunk.len();
            }
        }

        (items, cursor)
    }

    pub fn handle_patch(
        &mut self,
        patch: &crate::models::AIPatch,
        _root: &Path,
    ) -> (Option<StreamYieldItem>, Vec<String>) {
        let mut warnings = Vec::new();

        let resolution = self.resolve_path(&patch.llm_file_path, _root, &patch.search_content);

        if let Some(w) = resolution.0 {
            warnings.push(w.clone());
        }

        if let Some((path, fallback)) = resolution.1 {
            if let Some(fb) = fallback {
                self.overlay
                    .entry(path.clone())
                    .or_insert_with(|| fb.clone());
                self.discovered_baseline.entry(path.clone()).or_insert(fb);
            }

            let original = self
                .overlay
                .get(&path)
                .map(|s| s.as_str())
                .or_else(|| self.baseline.get(&path).map(|s| s.as_str()))
                .unwrap_or("");

            if let Some(new_content) =
                create_patched_content(original, &patch.search_content, &patch.replace_content)
            {
                let diff = generate_diff(&path, Some(original), Some(&new_content));
                self.overlay.insert(path.clone(), new_content.clone());
                (
                    Some(StreamYieldItem::DiffBlock(
                        crate::models::ProcessedDiffBlock {
                            llm_file_path: patch.llm_file_path.clone(),
                            unified_diff: diff,
                        },
                    )),
                    warnings,
                )
            } else {
                let msg = format!(
                    "The SEARCH block from the AI could not be found in '{}'. Patch skipped.",
                    path
                );
                warnings.push(msg.clone());
                (
                    Some(StreamYieldItem::Unparsed(crate::models::UnparsedBlock {
                        text: patch.raw_block.clone(),
                    })),
                    warnings,
                )
            }
        } else {
            let msg = format!(
                "File '{}' from the AI does not match any file in context. Patch skipped.",
                patch.llm_file_path
            );
            warnings.push(msg.clone());
            (
                Some(StreamYieldItem::Unparsed(crate::models::UnparsedBlock {
                    text: patch.raw_block.clone(),
                })),
                warnings,
            )
        }
    }

    pub fn finish(&mut self, last_chunk: &str) -> (String, Vec<StreamYieldItem>, Vec<String>) {
        // Process any final tokens received.
        self.feed(last_chunk);

        // Force flush if we are stuck waiting for a newline at EOF for a complete block
        if self.is_incomplete(&self.buffer)
            && self.buffer.contains("<<<<<<< SEARCH")
            && self.buffer.contains(">>>>>>> REPLACE")
        {
            self.buffer.push('\n');
        }

        let mut items: Vec<_> = self.by_ref().collect();

        // Anything remaining in the buffer is now considered a trailing segment.
        if !self.buffer.is_empty() {
            let looks_like_marker = self.is_incomplete(&self.buffer);

            if looks_like_marker {
                items.push(StreamYieldItem::Unparsed(UnparsedBlock {
                    text: self.buffer.clone(),
                }));
            } else {
                items.push(StreamYieldItem::Text(self.buffer.clone()));
            }
            self.buffer.clear();
        }

        let diff = self.build_final_unified_diff();

        let warnings = self.collect_warnings(&items);

        (diff, items, warnings)
    }

    pub fn collect_warnings(&self, items: &[StreamYieldItem]) -> Vec<String> {
        items
            .iter()
            .filter_map(|i| match i {
                StreamYieldItem::Warning(w) => Some(w.text.clone()),
                _ => None,
            })
            .collect()
    }

    /// Processes a list of raw yields, resolving any Patch items into DiffBlocks or Warnings.
    pub fn process_yields(
        &mut self,
        items: Vec<StreamYieldItem>,
        session_root: &Path,
    ) -> Vec<StreamYieldItem> {
        let mut processed = Vec::with_capacity(items.len());
        for item in items {
            if let StreamYieldItem::Patch(ref patch) = item {
                let (resolved, warnings) = self.handle_patch(patch, session_root);
                for w in warnings {
                    processed.push(StreamYieldItem::Warning(crate::models::WarningMessage {
                        text: w,
                    }));
                }
                if let Some(res) = resolved {
                    processed.push(res);
                }
            } else {
                processed.push(item);
            }
        }
        processed
    }

    pub fn build_final_unified_diff(&self) -> String {
        let mut diffs = String::new();
        let mut keys: Vec<&String> = self
            .discovered_baseline
            .keys()
            .chain(self.overlay.keys())
            .collect();
        keys.sort();
        keys.dedup();

        for k in keys {
            let old = self
                .discovered_baseline
                .get(k)
                .map(|s| s.as_str())
                .or_else(|| self.baseline.get(k).map(|s| s.as_str()));
            let new = self.overlay.get(k).map(|s| s.as_str());

            if old != new {
                let d = generate_diff(k, old, new);
                diffs.push_str(&d);
            }
        }
        diffs
    }

    fn resolve_path(
        &self,
        llm_path: &str,
        root: &Path,
        search_block: &str,
    ) -> (Option<String>, Option<(String, Option<String>)>) {
        if self.overlay.contains_key(llm_path) || self.baseline.contains_key(llm_path) {
            return (None, Some((llm_path.to_string(), None)));
        }
        if search_block.trim().is_empty() {
            return (None, Some((llm_path.to_string(), None)));
        }
        let abs_path = root.join(llm_path);
        if abs_path.exists()
            && let Ok(canon) = abs_path.canonicalize()
            && let Ok(root_canon) = root.canonicalize()
            && canon.starts_with(root_canon)
            && let Ok(content) = std::fs::read_to_string(&abs_path)
        {
            let msg = format!(
                "File '{}' was not in the session context but was found on disk.",
                llm_path
            );
            return (Some(msg), Some((llm_path.to_string(), Some(content))));
        }
        (None, None)
    }
}

fn consume_line_ending(s: &str) -> usize {
    if s.starts_with("\r\n") {
        2
    } else if s.starts_with('\n') {
        1
    } else {
        0
    }
}

fn find_marker_with_indent(
    chunk: &str,
    marker: &str,
    start_pos: usize,
    expected_indent: &str,
) -> Option<(usize, usize)> {
    let mut search_pos = start_pos;
    while let Some(i) = chunk[search_pos..].find(marker) {
        let found_idx = search_pos + i;
        let line_start = chunk[..found_idx]
            .rfind('\n')
            .map(|idx| idx + 1)
            .unwrap_or(0);
        if chunk[line_start..found_idx] == *expected_indent {
            let after = &chunk[found_idx + marker.len()..];
            let line_end = after
                .find('\n')
                .map(|idx| found_idx + marker.len() + idx)
                .unwrap_or(chunk.len());
            // We ignore \r here to allow CRLF support, checking only for \n as line terminator
            if chunk[found_idx + marker.len()..line_end]
                .chars()
                .all(|c| c.is_whitespace() && c != '\n')
            {
                return Some((line_start, line_end));
            }
        }
        search_pos = found_idx + marker.len();
    }
    None
}
