use crate::diffing::diff_utils::generate_diff;
use crate::diffing::patching::create_patched_content;
use crate::models::{StreamYieldItem, UnparsedBlock};
use regex::Regex;
use std::collections::HashMap;
use std::path::Path;
use std::sync::LazyLock;

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
    /// Tracks if the last yielded character was a newline.
    /// Used to enforce line-start anchors for headers.
    last_char_was_newline: bool,
}

impl<'a> StreamParser<'a> {
    pub fn get_pending_content(&self) -> String {
        self.buffer.clone()
    }

    pub fn is_pending_displayable(&self) -> bool {
        let pending = &self.buffer;
        if pending.is_empty() {
            return false;
        }

        let tail_is_at_line_start = if let Some(_) = pending.rfind('\n') {
            true
        } else {
            self.last_char_was_newline
        };

        if !tail_is_at_line_start {
            return true;
        }

        let last_line = pending.split('\n').next_back().unwrap_or("");
        let trimmed = last_line.trim_start();

        // 1. GLOBAL CHECK: File Headers
        // Block if the tail looks like the start of a "File:" line.
        if !trimmed.is_empty()
            && ("File:".starts_with(trimmed)
                || (trimmed.starts_with("File:") && !pending.ends_with('\n')))
        {
            return false;
        }

        // 2. CONTEXT CHECK: Diff Markers
        // We only care about diff markers if we are actively inside a file context.
        if self.current_file.is_some() {
            // A. Body Check: Are we buffering a block?
            // If the buffer contains the start marker, we are inside a block (or waiting for it to close).
            // We must hold back everything until the parser consumes it.
            if pending.contains("<<<<<<< SEARCH") {
                return false;
            }

            // B. Tail Check: Is a block starting right now?
            // We ONLY need to check for the start marker.
            // (We don't check for ======= or >>>>>>> because if we see those WITHOUT
            // the start marker in the body check above, they are just text).
            if !trimmed.is_empty() && "<<<<<<< SEARCH".starts_with(trimmed) {
                return false;
            }
        }

        true
    }

    pub fn new(original_contents: &'a HashMap<String, String>) -> Self {
        Self {
            buffer: String::new(),
            current_file: None,
            yield_queue: std::collections::VecDeque::new(),
            baseline: original_contents,
            overlay: HashMap::new(),
            discovered_baseline: HashMap::new(),
            // Start of stream is treated as start of a line
            last_char_was_newline: true,
        }
    }

    /// Feeds a new chunk of text into the parser.
    /// Use the Iterator implementation (next()) to retrieve yielded items.
    pub fn feed(&mut self, chunk: &str) {
        self.buffer.push_str(chunk);
    }

    /// Feeds content ensuring a trailing newline for correct parsing of final blocks.
    pub fn feed_complete(&mut self, content: &str) {
        self.feed(content);
        if !content.ends_with('\n') {
            self.feed("\n");
        }
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

    fn update_newline_state(&mut self, item: &StreamYieldItem) {
        match item {
            StreamYieldItem::Text(s) => self.last_char_was_newline = s.ends_with('\n'),
            StreamYieldItem::Unparsed(u) => self.last_char_was_newline = u.text.ends_with('\n'),
            StreamYieldItem::FileHeader(_) => self.last_char_was_newline = true, // Headers end with \n
            StreamYieldItem::Patch(p) => self.last_char_was_newline = p.raw_block.ends_with('\n'),
            StreamYieldItem::DiffBlock(d) => {
                self.last_char_was_newline = d.unified_diff.ends_with('\n')
            }
            StreamYieldItem::Warning(_) => {} // Metadata doesn't affect flow
            StreamYieldItem::IncompleteBlock(b) => self.last_char_was_newline = b.ends_with('\n'),
        }
    }
}

static FILE_HEADER_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?m)^(?P<line>[ \t]*File:[ \t]*(?P<path>.*?)\r?\n)").unwrap());

impl<'a> Iterator for StreamParser<'a> {
    type Item = StreamYieldItem;

    fn next(&mut self) -> Option<Self::Item> {
        loop {
            // 1. First, drain the pre-parsed queue
            if let Some(item) = self.yield_queue.pop_front() {
                self.update_newline_state(&item);
                return Some(item);
            }

            if self.buffer.is_empty() {
                return None;
            }

            // 2. If we are currently "inside" a file's content section
            if let Some(llm_file_path) = self.current_file.clone() {
                // Find potential headers
                let mut next_header_idx = self.buffer.len();
                for m in FILE_HEADER_RE.find_iter(&self.buffer) {
                    // Valid header must be at > 0 (newline preceding) OR at 0 with newline state
                    if m.start() > 0 || self.last_char_was_newline {
                        next_header_idx = m.start();
                        break;
                    }
                    // If m.start() == 0 && !last_char_was_newline, it's a false positive.
                    // We skip it and treat it as part of the file content.
                }

                if next_header_idx > 0 || (next_header_idx == 0 && self.last_char_was_newline) {
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

                // If we found a valid header (and aren't stuck waiting for chunks)
                if next_header_idx < self.buffer.len() {
                    self.current_file = None;
                    continue;
                }
            }

            // 3. Look for Global File Headers
            if let Some(caps) = FILE_HEADER_RE.captures(&self.buffer) {
                let mat = caps.get(0).unwrap();
                let is_valid_match = mat.start() > 0 || self.last_char_was_newline;

                if is_valid_match {
                    if mat.start() > 0 {
                        let text = self.buffer[..mat.start()].to_string();
                        self.buffer.drain(..mat.start());
                        let item = StreamYieldItem::Text(text);
                        self.update_newline_state(&item);
                        return Some(item);
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
                    let item = StreamYieldItem::FileHeader(crate::models::FileHeader {
                        llm_file_path: path_str,
                    });
                    self.update_newline_state(&item);
                    return Some(item);
                }
                // If invalid match (at 0 but !newline), fall through to Text handling
            }

            // 4. Handle remaining buffer as Markdown Text
            let text = &self.buffer;
            let mut stable_len = text.len();

            if self.is_incomplete(text) {
                // Check if we are holding back for a file header
                if let Some(m) = FILE_HEADER_RE.find(text) {
                    // Only respect valid headers
                    if m.start() > 0 || self.last_char_was_newline {
                        stable_len = m.start();
                    }
                } else if let Some(search_idx) = text.find("<<<<<<< SEARCH") {
                    // Only respect diff markers if line-start (handled by is_incomplete logic?)
                    // Logic here simplifies assuming is_incomplete did the heavy lifting
                    // But we must calculate stable_len correctly.
                    stable_len = text[..search_idx].rfind('\n').map(|i| i + 1).unwrap_or(0);
                    if stable_len == 0 && !self.last_char_was_newline {
                        // Marker at 0 but not newline -> Ignore marker, yield text
                        stable_len = text.len();
                    }
                } else if let Some(last_newline) = text.rfind('\n') {
                    let last_line = &text[last_newline + 1..];
                    if self.is_incomplete(last_line) {
                        stable_len = last_newline + 1;
                    }
                } else {
                    // No newlines.
                    // If is_incomplete returned true, it means !tail_is_at_line_start check passed?
                    // No, if no newlines and !last_char_was_newline, is_incomplete returns false.
                    // So if we are here, either last_char_was_newline IS true, OR is_incomplete found something else.
                    stable_len = 0;
                }
            }

            if stable_len > 0 {
                let text_yield = self.buffer[..stable_len].to_string();
                self.buffer.drain(..stable_len);
                let item = StreamYieldItem::Text(text_yield);
                self.update_newline_state(&item);
                return Some(item);
            }

            return None;
        }
    }
}

impl<'a> StreamParser<'a> {
    fn is_incomplete(&self, text: &str) -> bool {
        // Optimization: If we are not at the start of a line, we can't match headers/markers.
        let tail_is_at_line_start = if let Some(_) = text.rfind('\n') {
            true
        } else {
            self.last_char_was_newline
        };

        if !tail_is_at_line_start {
            return false;
        }

        // 1. GLOBAL CHECK: File Headers
        // Check for partial "File:" header at the end of the buffer
        if let Some(last_line) = text.split('\n').next_back() {
            let trimmed = last_line.trim_start();
            if !trimmed.is_empty()
                && ("File:".starts_with(trimmed)
                    || (trimmed.starts_with("File:") && !text.ends_with('\n')))
            {
                return true;
            }
        }

        // 2. CONTEXT CHECK: Diff Markers
        // Only check for markers if we are inside a file
        if self.current_file.is_some() {
            // Check if we are inside an unclosed SEARCH block
            if let Some(idx) = text.find("<<<<<<< SEARCH") {
                let line_start = text[..idx].rfind('\n').map(|i| i + 1).unwrap_or(0);
                // If start is 0, check newline state
                if line_start == 0 && !text.contains('\n') && !self.last_char_was_newline {
                    // Mid-line marker match -> Invalid. Ignore.
                } else {
                    let indent = &text[line_start..idx];
                    // Only consider it a block if indent is pure whitespace and it hasn't been closed yet
                    if indent.chars().all(|c| c.is_whitespace())
                        && !text.contains(">>>>>>> REPLACE")
                    {
                        return true;
                    }
                }
            }

            // Check for partial markers at the end
            if let Some(last_line) = text.split('\n').next_back() {
                let trimmed = last_line.trim_start();
                if !trimmed.is_empty() && "<<<<<<< SEARCH".starts_with(trimmed) {
                    return true;
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
            let indent_slice = &chunk[line_start..search_idx];

            // Verify indent consists only of whitespace
            if !indent_slice.chars().all(|c| c.is_whitespace()) {
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
                match find_marker_with_indent(chunk, sep_pattern, block_search_start, indent_slice)
                {
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
                match find_marker_with_indent(chunk, replace_pattern, sep_line_end, indent_slice) {
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

            let final_end = replace_line_start + indent_slice.len() + replace_pattern.len();

            let search_content = &chunk[block_search_start_content..sep_line_start];
            let replace_content = &chunk[block_replace_start_content..replace_line_start];

            items.push(StreamYieldItem::Patch(crate::models::AIPatch {
                llm_file_path: llm_path.to_string(),
                search_content: search_content.to_string(),
                replace_content: replace_content.to_string(),
                indent: indent_slice.to_string(),
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
                warnings.push(format!(
                    "The SEARCH block from the AI could not be found in '{}'. Patch skipped.",
                    path
                ));

                (
                    Some(StreamYieldItem::Unparsed(crate::models::UnparsedBlock {
                        text: patch.raw_block.clone(),
                    })),
                    warnings,
                )
            }
        } else {
            warnings.push(format!(
                "File '{}' from the AI does not match any file in context. Patch skipped.",
                patch.llm_file_path
            ));

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
        let keys: std::collections::BTreeSet<_> = self
            .discovered_baseline
            .keys()
            .chain(self.overlay.keys())
            .collect();

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
