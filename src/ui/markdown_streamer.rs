// This implementation is loosly based on https://github.com/day50-dev/Streamdown
use crate::console::ANSI_REGEX_PATTERN;
use crossterm::{
    queue,
    style::{
        Attribute, Color, Print, ResetColor, SetAttribute, SetBackgroundColor, SetForegroundColor,
    },
};
use regex::Regex;
use std::fmt::Write as _;
use std::io::{self, Write};
use std::sync::LazyLock;
use syntect::easy::HighlightLines;
use syntect::highlighting::{Theme, ThemeSet};
use syntect::parsing::SyntaxSet;
use unicode_width::UnicodeWidthStr;

// --- Static Resources ---
static SYNTAX_SET: LazyLock<SyntaxSet> = LazyLock::new(SyntaxSet::load_defaults_newlines);
static THEME: LazyLock<Theme> = LazyLock::new(|| {
    let ts = ThemeSet::load_defaults();
    ts.themes
        .get("base16-ocean.dark")
        .or_else(|| ts.themes.values().next())
        .expect("No themes found")
        .clone()
});

// Regexes
static RE_CODE_FENCE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(\s*)([`~]{3,})(.*)$").unwrap());
static RE_HEADER: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(#{1,6})\s+(.*)").unwrap());
static RE_HR: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(\s*[-*_]){3,}\s*$").unwrap());
static RE_LIST: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(\s*)([-*+]|\d+\.)(?:(\s+)(.*)|$)").unwrap());
static RE_BLOCKQUOTE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(\s*>\s?)(.*)").unwrap());

static RE_TABLE_ROW: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\s*\|(.*)\|\s*$").unwrap());
static RE_TABLE_SEP: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[\s\|\-\:]+$").unwrap());

static RE_MATH_BLOCK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\s*\$\$\s*$").unwrap());

// Single pattern for "Invisible" content (ANSI codes + OSC8 links) used for width calculation
static RE_INVISIBLE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!("({}|{})", OSC8_PATTERN, ANSI_REGEX_PATTERN)).unwrap());

// --- ANSI & Links ---
// Shared pattern for OSC 8 links: \x1b]8;; ... \x1b\
const OSC8_PATTERN: &str = r"\x1b]8;;.*?\x1b\\";

static RE_LINK: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\[([^\]]+)\]\(([^\)]+)\)").unwrap());
static RE_OSC8: LazyLock<Regex> = LazyLock::new(|| Regex::new(OSC8_PATTERN).unwrap());

static RE_TOKENIZER: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(
        r"({}|{}|`+|\\[\s\S]|\$[^\$\s](?:[^\$\n]*?[^\$\s])?\$|~~|~|\*\*\*|___|\*\*|__|\*|_|\$|[^~*_`$\\\x1b]+)",
        OSC8_PATTERN, ANSI_REGEX_PATTERN
    ))
    .unwrap()
});

static RE_SPLIT_ANSI: LazyLock<Regex> = LazyLock::new(|| {
    let pattern = format!(
        "({}|{}|\\s+|[^\\s\\x1b]+)",
        OSC8_PATTERN, ANSI_REGEX_PATTERN
    );
    Regex::new(&pattern).unwrap()
});
static RE_ANSI_PARTS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\x1b\[([0-9;]*)m").unwrap());

// --- Helper Structs ---

struct InlinePart {
    content: String,
    is_delim: bool,
    char: char,
    len: usize,
    can_open: bool,
    can_close: bool,
    pre_style: Vec<String>,
    post_style: Vec<String>,
}

impl InlinePart {
    fn text(content: String) -> Self {
        Self {
            content,
            is_delim: false,
            char: '\0',
            len: 0,
            can_open: false,
            can_close: false,
            pre_style: vec![],
            post_style: vec![],
        }
    }
}

pub struct MarkdownStreamer {
    // Code State
    active_fence: Option<(char, usize, usize)>, // char, min_len, indent
    code_lang: String,

    // Inline Code State
    inline_code_ticks: Option<usize>,
    inline_code_buffer: String,

    // Math State
    in_math_block: bool,
    math_buffer: String,

    // Table State
    in_table: bool,
    table_header_printed: bool,

    // Parsing State
    highlighter: Option<HighlightLines<'static>>,
    line_buffer: String,

    // Layout State
    margin: usize,
    blockquote_depth: usize,
    list_stack: Vec<(usize, bool, usize, usize)>, // (indent_len, is_ordered, counter, marker_width)
    pending_newline: bool,

    // Configuration
    manual_width: Option<usize>,

    // Reusable buffer
    scratch_buffer: String,
}

impl Default for MarkdownStreamer {
    fn default() -> Self {
        Self::new()
    }
}

impl MarkdownStreamer {
    pub fn new() -> Self {
        Self {
            active_fence: None,
            code_lang: "bash".to_string(),
            inline_code_ticks: None,
            inline_code_buffer: String::new(),
            in_math_block: false,
            math_buffer: String::new(),
            in_table: false,
            table_header_printed: false,
            highlighter: None,
            line_buffer: String::new(),
            margin: 2,
            blockquote_depth: 0,
            list_stack: Vec::new(),
            pending_newline: false,
            manual_width: None,
            scratch_buffer: String::with_capacity(1024),
        }
    }

    /// Set a fixed width for rendering. If not set, terminal size is queried.
    pub fn set_width(&mut self, width: usize) {
        self.manual_width = Some(width);
    }

    /// Set the margin (default 2)
    pub fn set_margin(&mut self, margin: usize) {
        self.margin = margin;
    }

    fn get_width(&self) -> usize {
        self.manual_width
            .unwrap_or_else(crate::console::get_terminal_width)
    }

    fn visible_width(&self, text: &str) -> usize {
        UnicodeWidthStr::width(RE_INVISIBLE.replace_all(text, "").as_ref())
    }

    /// Main entry point: Process a chunk of text and write to the provided writer.
    pub fn print_chunk<W: Write>(&mut self, writer: &mut W, text: &str) -> io::Result<()> {
        self.line_buffer.push_str(text);
        while let Some(pos) = self.line_buffer.find('\n') {
            let line = self.line_buffer[..pos + 1].to_string();
            self.line_buffer.drain(..pos + 1);
            self.process_line(writer, &line)?;
        }
        Ok(())
    }

    /// Flush remaining buffer (useful at end of stream).
    pub fn flush<W: Write>(&mut self, writer: &mut W) -> io::Result<()> {
        if !self.line_buffer.is_empty() {
            let line = std::mem::take(&mut self.line_buffer);
            self.process_line(writer, &line)?;
        }

        self.flush_pending_inline(writer)?;
        self.commit_newline(writer)?;
        writer.flush()
    }

    fn commit_newline<W: Write>(&mut self, writer: &mut W) -> io::Result<()> {
        if self.pending_newline {
            queue!(writer, Print("\n"))?;
            self.pending_newline = false;
        }
        Ok(())
    }

    fn flush_pending_inline<W: Write>(&mut self, writer: &mut W) -> io::Result<()> {
        if let Some(ticks) = self.inline_code_ticks {
            // Print the opening ticks
            queue!(writer, Print("`".repeat(ticks)))?;
            // Print the buffer content
            queue!(writer, Print(&self.inline_code_buffer))?;
            self.inline_code_ticks = None;
            self.inline_code_buffer.clear();
        }
        Ok(())
    }

    // --- Pipeline Controller ---
    fn process_line<W: Write>(&mut self, w: &mut W, raw_line: &str) -> io::Result<()> {
        let expanded = raw_line.replace('\t', "  ");
        let trimmed = expanded.trim_end();

        // 1. Context-Specific Handlers (return true if consumed)
        if self.try_handle_fence(w, &expanded, trimmed)? {
            return Ok(());
        }
        if self.try_handle_math(w, trimmed)? {
            return Ok(());
        }
        if self.try_handle_table(w, trimmed)? {
            return Ok(());
        }

        // 2. Global Layout Calculation (Blockquotes & Margins)
        let mut content = expanded.as_str();
        self.blockquote_depth = 0;
        while let Some(caps) = RE_BLOCKQUOTE.captures(content) {
            self.blockquote_depth += 1;
            content = caps.get(2).map_or("", |m| m.as_str());
        }

        let mut prefix = " ".repeat(self.margin);
        if self.blockquote_depth > 0 {
            prefix.push_str("\x1b[38;5;240m");
            for _ in 0..self.blockquote_depth {
                prefix.push_str("│ ");
            }
            prefix.push_str("\x1b[0m");
        }

        let term_width = self.get_width();
        let prefix_width = self.margin + (self.blockquote_depth * 2);
        let avail_width = term_width.saturating_sub(prefix_width + self.margin);

        // 3. Block Start Handlers
        // Note: Block handlers must now check for pending inline code and flush it
        // if the block structure interrupts the inline span (Spec 6.1).
        let clean = content.trim_end();
        if self.try_handle_header(w, clean, &prefix, avail_width)? {
            return Ok(());
        }
        if self.try_handle_hr(w, clean, &prefix, avail_width)? {
            return Ok(());
        }
        if self.try_handle_list(w, clean, &prefix, avail_width)? {
            return Ok(());
        }

        // 4. Standard Text / Lazy Continuation
        self.render_standard_text(w, content, &prefix, avail_width)
    }

    // --- Specific Handlers ---

    fn try_handle_fence<W: Write>(
        &mut self,
        w: &mut W,
        full: &str,
        trimmed: &str,
    ) -> io::Result<bool> {
        let match_data = RE_CODE_FENCE.captures(trimmed);

        // Closing Fence
        if let Some((f_char, min_len, _)) = self.active_fence {
            if let Some(caps) = &match_data {
                let fence = &caps[2];
                if fence.starts_with(f_char) && fence.len() >= min_len && caps[3].trim().is_empty()
                {
                    self.active_fence = None;
                    self.commit_newline(w)?;
                    queue!(w, ResetColor)?;
                    self.pending_newline = true;
                    return Ok(true);
                }
            }
            self.render_code_line(w, full)?;
            return Ok(true);
        }

        // Opening Fence
        if let Some(caps) = match_data {
            let fence = &caps[2];
            let indent_len = caps[1].len();
            let info = caps[3].trim();
            if let Some(f_char) = fence.chars().next()
                && (f_char != '`' || !info.contains('`'))
            {
                self.flush_pending_inline(w)?;
                self.commit_newline(w)?;
                while self
                    .list_stack
                    .last()
                    .is_some_and(|(d, _, _, _)| *d > indent_len)
                {
                    self.list_stack.pop();
                }
                self.active_fence = Some((f_char, fence.len(), indent_len));
                let lang = info.split_whitespace().next().unwrap_or("bash");
                self.code_lang = lang.to_string();
                self.start_highlighter(&self.code_lang.clone());
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn try_handle_math<W: Write>(&mut self, w: &mut W, trimmed: &str) -> io::Result<bool> {
        if RE_MATH_BLOCK.is_match(trimmed) {
            if self.in_math_block {
                self.in_math_block = false;
                let converted = unicodeit::replace(&self.math_buffer);
                let p_width = self.margin + (self.blockquote_depth * 2);
                let avail = self.get_width().saturating_sub(p_width + self.margin);
                let padding = avail.saturating_sub(self.visible_width(&converted)) / 2;

                self.commit_newline(w)?;
                queue!(
                    w,
                    Print(" ".repeat(self.margin + padding)),
                    SetForegroundColor(Color::Cyan),
                    SetAttribute(Attribute::Italic),
                    Print(converted),
                    ResetColor,
                    SetAttribute(Attribute::Reset)
                )?;
                self.pending_newline = true;
                self.math_buffer.clear();
            } else {
                self.flush_pending_inline(w)?;
                self.commit_newline(w)?;
                self.reset_block_context();
                self.in_math_block = true;
            }
            return Ok(true);
        }
        if self.in_math_block {
            self.math_buffer.push_str(trimmed);
            self.math_buffer.push(' ');
            return Ok(true);
        }
        Ok(false)
    }

    fn try_handle_table<W: Write>(&mut self, w: &mut W, trimmed: &str) -> io::Result<bool> {
        if self.in_table && RE_TABLE_SEP.is_match(trimmed) {
            self.table_header_printed = true;
            return Ok(true);
        }
        if RE_TABLE_ROW.is_match(trimmed) {
            if !self.in_table {
                self.flush_pending_inline(w)?;
                self.commit_newline(w)?;
                self.reset_block_context();
                self.in_table = true;
            }
            self.render_stream_table_row(w, trimmed)?;
            return Ok(true);
        }
        self.in_table = false;
        self.table_header_printed = false;
        Ok(false)
    }

    fn try_handle_header<W: Write>(
        &mut self,
        w: &mut W,
        clean: &str,
        prefix: &str,
        avail: usize,
    ) -> io::Result<bool> {
        if let Some(caps) = RE_HEADER.captures(clean) {
            self.flush_pending_inline(w)?;
            self.commit_newline(w)?;
            let level = caps.get(1).map_or(0, |m| m.len());
            let text = caps.get(2).map_or("", |m| m.as_str());
            self.reset_block_context();

            queue!(w, Print(prefix))?;
            if level <= 2 {
                queue!(w, Print("\n"))?;
            }

            self.scratch_buffer.clear();
            let style = match level {
                1 => "\x1b[1m",
                2 => "\x1b[1;94m",
                3 => "\x1b[1;36m",
                _ => "\x1b[1;33m",
            };
            self.render_inline(text, None, Some(style));

            if level <= 2 {
                let lines = self.wrap_ansi(&self.scratch_buffer, avail);
                for line in lines {
                    let pad = avail.saturating_sub(self.visible_width(&line)) / 2;
                    queue!(
                        w,
                        Print(" ".repeat(pad)),
                        Print(format!("{}{}\x1b[0m", style, line)),
                        ResetColor,
                        Print("\n")
                    )?;
                    if level == 1 {
                        queue!(w, Print(prefix))?;
                    }
                }
            } else {
                queue!(
                    w,
                    Print(style),
                    Print(&self.scratch_buffer),
                    Print("\x1b[0m")
                )?;
                self.pending_newline = true;
            }
            return Ok(true);
        }
        Ok(false)
    }

    fn try_handle_list<W: Write>(
        &mut self,
        w: &mut W,
        clean: &str,
        prefix: &str,
        avail: usize,
    ) -> io::Result<bool> {
        if let Some(caps) = RE_LIST.captures(clean) {
            self.flush_pending_inline(w)?;
            self.commit_newline(w)?;
            let indent = caps.get(1).map_or(0, |m| m.len());
            let bullet = caps.get(2).map_or("-", |m| m.as_str());
            let separator = caps.get(3).map_or(" ", |m| m.as_str());
            let text = caps.get(4).map_or("", |m| m.as_str());

            let is_ord = bullet.chars().any(|c| c.is_numeric());
            let disp_bullet = if is_ord { bullet } else { "•" };
            let marker_width = self.visible_width(disp_bullet) + separator.len();

            let last_indent = self.list_stack.last().map(|(d, _, _, _)| *d).unwrap_or(0);
            if self.list_stack.is_empty() || indent > last_indent {
                self.list_stack.push((indent, is_ord, 0, marker_width));
            } else if indent < last_indent {
                while self
                    .list_stack
                    .last()
                    .is_some_and(|(d, _, _, _)| *d > indent)
                {
                    self.list_stack.pop();
                }
                if self
                    .list_stack
                    .last()
                    .is_some_and(|(d, _, _, _)| *d != indent)
                {
                    self.list_stack.push((indent, is_ord, 0, marker_width));
                }
            } else {
                // Same level: update width in case marker size changed (e.g. 9. -> 10.)
                if let Some(last) = self.list_stack.last_mut() {
                    last.3 = marker_width;
                }
            }

            let full_stack_width: usize = self.list_stack.iter().map(|(_, _, _, w)| *w).sum();
            let parent_width = full_stack_width.saturating_sub(marker_width);

            let hang_indent = " ".repeat(full_stack_width);
            let content_width = avail.saturating_sub(full_stack_width);

            queue!(
                w,
                Print(prefix),
                Print(" ".repeat(parent_width)),
                SetForegroundColor(Color::Yellow),
                Print(disp_bullet),
                Print(separator),
                ResetColor
            )?;

            // Check if the text portion looks like a code fence start (e.g., "```ruby")
            if let Some(fcaps) = RE_CODE_FENCE.captures(text) {
                queue!(w, Print("\n"))?;

                let fence_chars = &fcaps[2];
                let info = fcaps[3].trim();

                if let Some(f_char) = fence_chars.chars().next() {
                    self.active_fence = Some((f_char, fence_chars.len(), 0));

                    let lang = info.split_whitespace().next().unwrap_or("bash");
                    self.code_lang = lang.to_string();
                    self.start_highlighter(&self.code_lang.clone());
                }
                return Ok(true);
            }

            self.scratch_buffer.clear();
            self.render_inline(text, None, None);
            let lines = self.wrap_ansi(&self.scratch_buffer, content_width);

            if lines.is_empty() {
                self.pending_newline = true;
            } else {
                for (i, line) in lines.iter().enumerate() {
                    if i > 0 {
                        queue!(w, Print("\n"), Print(prefix), Print(&hang_indent))?;
                    }
                    queue!(w, Print(line), ResetColor)?;
                }
                self.pending_newline = true;
            }
            return Ok(true);
        }
        Ok(false)
    }

    fn try_handle_hr<W: Write>(
        &mut self,
        w: &mut W,
        clean: &str,
        prefix: &str,
        avail: usize,
    ) -> io::Result<bool> {
        if RE_HR.is_match(clean) {
            self.flush_pending_inline(w)?;
            self.commit_newline(w)?;
            queue!(
                w,
                Print(prefix),
                SetForegroundColor(Color::DarkGrey),
                Print("─".repeat(avail)),
                ResetColor
            )?;
            self.pending_newline = true;
            self.reset_block_context();
            return Ok(true);
        }
        Ok(false)
    }

    fn render_standard_text<W: Write>(
        &mut self,
        w: &mut W,
        content: &str,
        prefix: &str,
        avail: usize,
    ) -> io::Result<()> {
        self.commit_newline(w)?;
        let mut line_content = content.trim_end_matches(['\n', '\r']);
        if line_content.trim().is_empty() && content.ends_with('\n') {
            self.reset_block_context();
            if self.blockquote_depth > 0 {
                queue!(w, Print(prefix))?;
            }
            self.pending_newline = true;
            return Ok(());
        }

        if !line_content.is_empty() || self.inline_code_ticks.is_some() {
            let mut eff_prefix = prefix.to_string();
            if !self.list_stack.is_empty() {
                let current_indent = line_content.chars().take_while(|c| *c == ' ').count();
                if current_indent == 0 {
                    self.list_stack.clear();
                } else {
                    while self
                        .list_stack
                        .last()
                        .is_some_and(|(d, _, _, _)| *d > current_indent)
                    {
                        self.list_stack.pop();
                    }
                }

                if !self.list_stack.is_empty() {
                    let structural_indent: usize =
                        self.list_stack.iter().map(|(_, _, _, w)| *w).sum();
                    eff_prefix.push_str(&" ".repeat(structural_indent));

                    // To avoid double-indenting, we skip the source indentation that matches
                    // the structural indentation we just applied via eff_prefix.
                    let skip = current_indent.min(structural_indent);
                    line_content = &line_content[skip..];
                }
            }

            self.scratch_buffer.clear();
            self.render_inline(line_content, None, None);
            if self.inline_code_ticks.is_some() {
                self.inline_code_buffer.push(' ');
            }

            let lines = self.wrap_ansi(&self.scratch_buffer, avail);
            for (i, line) in lines.iter().enumerate() {
                if i > 0 {
                    queue!(w, Print("\n"))?;
                }
                queue!(
                    w,
                    ResetColor,
                    SetAttribute(Attribute::Reset),
                    Print(&eff_prefix),
                    Print(line),
                    ResetColor
                )?;
            }
            if !lines.is_empty() {
                self.pending_newline = true;
            }
        }
        Ok(())
    }

    fn reset_block_context(&mut self) {
        self.list_stack.clear();
        self.table_header_printed = false;
    }

    fn wrap_ansi(&self, text: &str, width: usize) -> Vec<String> {
        let mut lines = Vec::new();
        let mut current_line = String::new();
        let mut current_len = 0;
        let mut active_codes: Vec<String> = Vec::new();

        for caps in RE_SPLIT_ANSI.captures_iter(text) {
            let token = caps.get(1).unwrap().as_str();
            if token.starts_with("\x1b") {
                current_line.push_str(token);
                // If it's an OSC8 link sequence, it has no visible width.
                // update_ansi_state already ignores it for state tracking, but we must
                // ensure we don't accidentally treat it as visible text below.
                self.update_ansi_state(&mut active_codes, token);
            } else {
                let mut token_str = token;
                let mut token_len = UnicodeWidthStr::width(token_str);

                while current_len + token_len > width && width > 0 {
                    if current_len == 0 {
                        // Force split long word
                        let mut split_idx = 0;
                        let mut split_len = 0;
                        for (idx, c) in token_str.char_indices() {
                            let c_w = UnicodeWidthStr::width(c.to_string().as_str());
                            if split_len + c_w > width {
                                break;
                            }
                            split_idx = idx + c.len_utf8();
                            split_len += c_w;
                        }
                        if split_idx == 0 {
                            split_idx = token_str.chars().next().map_or(0, |c| c.len_utf8());
                        }
                        if split_idx == 0 {
                            break;
                        } // Empty string safety

                        current_line.push_str(&token_str[..split_idx]);
                        lines.push(current_line);
                        current_line = active_codes.join("");
                        token_str = &token_str[split_idx..];
                        token_len = UnicodeWidthStr::width(token_str);
                        current_len = 0;
                    } else if !token_str.trim().is_empty() {
                        lines.push(current_line);
                        current_line = active_codes.join("");
                        current_len = 0;
                    } else {
                        token_str = "";
                        token_len = 0;
                    }
                }
                if !token_str.is_empty() {
                    current_line.push_str(token_str);
                    current_len += token_len;
                }
            }
        }
        if !current_line.is_empty() {
            lines.push(current_line);
        }
        lines
    }

    fn update_ansi_state(&self, state: &mut Vec<String>, code: &str) {
        if RE_OSC8.is_match(code) {
            return;
        }
        if let Some(caps) = RE_ANSI_PARTS.captures(code) {
            let content = caps.get(1).map_or("", |m| m.as_str());
            if content == "0" || content.is_empty() {
                state.clear();
                return;
            }

            let num: i32 = content
                .split(';')
                .next()
                .unwrap_or("0")
                .parse()
                .unwrap_or(0);
            let category = match num {
                1 | 22 => "bold",
                3 | 23 => "italic",
                4 | 24 => "underline",
                30..=39 | 90..=97 => "fg",
                40..=49 | 100..=107 => "bg",
                _ => "other",
            };
            if category != "other" {
                state.retain(|exist| {
                    let e_num: i32 = RE_ANSI_PARTS
                        .captures(exist)
                        .and_then(|c| c.get(1))
                        .map_or("0", |m| m.as_str())
                        .split(';')
                        .next()
                        .unwrap_or("0")
                        .parse()
                        .unwrap_or(0);
                    let e_cat = match e_num {
                        1 | 22 => "bold",
                        3 | 23 => "italic",
                        4 | 24 => "underline",
                        30..=39 | 90..=97 => "fg",
                        40..=49 | 100..=107 => "bg",
                        _ => "other",
                    };
                    e_cat != category
                });
            }
            state.push(code.to_string());
        }
    }

    fn render_code_line<W: Write>(&mut self, w: &mut W, line: &str) -> io::Result<()> {
        self.commit_newline(w)?;
        let raw_line = line.trim_end_matches(&['\r', '\n'][..]);

        let fence_indent = self.active_fence.map(|(_, _, i)| i).unwrap_or(0);

        // Strip the fence's indentation from the content line
        let mut chars = raw_line.chars();
        let mut skipped = 0;
        while skipped < fence_indent {
            let as_str = chars.as_str();
            if as_str.starts_with(' ') {
                chars.next();
                skipped += 1;
            } else {
                break;
            }
        }
        let line_content = chars.as_str();

        let mut prefix = " ".repeat(self.margin);
        if !self.list_stack.is_empty() {
            let indent_width: usize = self.list_stack.iter().map(|(_, _, _, w)| *w).sum();
            prefix.push_str(&" ".repeat(indent_width));
        }

        let avail_width = self.get_width().saturating_sub(prefix.len() + self.margin);

        let mut spans = Vec::new();
        if let Some(h) = &mut self.highlighter {
            if let Ok(ranges) = h.highlight_line(line_content, &SYNTAX_SET) {
                spans = ranges;
            } else {
                spans.push((syntect::highlighting::Style::default(), line_content));
            }
        } else {
            spans.push((syntect::highlighting::Style::default(), line_content));
        }

        // 1. Build the full colored line in memory first
        self.scratch_buffer.clear();
        for (style, text) in spans {
            let _ = write!(
                self.scratch_buffer,
                "\x1b[38;2;{};{};{}m{}",
                style.foreground.r, style.foreground.g, style.foreground.b, text
            );
        }

        // 2. Wrap the colored string manually
        let wrapped_lines = self.wrap_ansi(&self.scratch_buffer, avail_width);

        // 3. Render each wrapped segment with consistent background
        if wrapped_lines.is_empty() {
            queue!(
                w,
                Print(&prefix),
                SetBackgroundColor(Color::Rgb {
                    r: 30,
                    g: 30,
                    b: 30
                }),
                Print(" ".repeat(avail_width)),
                ResetColor
            )?;
        } else {
            for (i, line) in wrapped_lines.iter().enumerate() {
                if i > 0 {
                    queue!(w, Print("\n"))?;
                }
                let vis_len = self.visible_width(line);
                let pad = avail_width.saturating_sub(vis_len);

                queue!(
                    w,
                    Print(&prefix),
                    SetBackgroundColor(Color::Rgb {
                        r: 30,
                        g: 30,
                        b: 30
                    }),
                    Print(line),
                    Print(" ".repeat(pad)), // Fill remaining width with bg color
                    ResetColor
                )?;
            }
        }
        self.pending_newline = true;
        Ok(())
    }

    fn render_stream_table_row<W: Write>(&mut self, w: &mut W, row_str: &str) -> io::Result<()> {
        self.commit_newline(w)?;
        let term_width = self.get_width();
        let cells: Vec<&str> = row_str.trim().trim_matches('|').split('|').collect();
        if cells.is_empty() {
            return Ok(());
        }

        let prefix_width = self.margin + (self.blockquote_depth * 2);
        let avail = term_width.saturating_sub(prefix_width + self.margin + 1 + (cells.len() * 3));
        if avail == 0 {
            return Ok(());
        }
        let base_w = avail / cells.len();
        let rem = avail % cells.len();

        let bg = if !self.table_header_printed {
            Color::Rgb {
                r: 60,
                g: 60,
                b: 80,
            }
        } else {
            Color::Rgb {
                r: 30,
                g: 30,
                b: 30,
            }
        };
        let mut wrapped_cells = Vec::new();
        let mut max_h = 1;

        for (i, cell) in cells.iter().enumerate() {
            let width = std::cmp::max(
                1,
                if i == cells.len() - 1 {
                    base_w + rem
                } else {
                    base_w
                },
            );
            self.scratch_buffer.clear();
            if !self.table_header_printed {
                self.scratch_buffer.push_str("\x1b[1;33m");
            }
            self.render_inline(
                cell.trim(),
                Some(bg),
                if !self.table_header_printed {
                    Some("\x1b[1;33m")
                } else {
                    None
                },
            );
            if !self.table_header_printed {
                self.scratch_buffer.push_str("\x1b[0m");
            }

            let lines = self.wrap_ansi(&self.scratch_buffer, width);
            if lines.len() > max_h {
                max_h = lines.len();
            }
            wrapped_cells.push((lines, width));
        }

        let mut prefix = " ".repeat(self.margin);
        if self.blockquote_depth > 0 {
            prefix.push_str("\x1b[38;5;240m");
            for _ in 0..self.blockquote_depth {
                prefix.push_str("│ ");
            }
            prefix.push_str("\x1b[0m");
        }

        for i in 0..max_h {
            if i > 0 {
                queue!(w, Print("\n"))?;
            }
            queue!(w, Print(&prefix))?;
            for (col, (lines, width)) in wrapped_cells.iter().enumerate() {
                let text = lines.get(i).map(|s| s.as_str()).unwrap_or("");
                let pad = width.saturating_sub(self.visible_width(text));
                queue!(
                    w,
                    SetBackgroundColor(bg),
                    Print(" "),
                    Print(text),
                    SetBackgroundColor(bg),
                    Print(" ".repeat(pad + 1)),
                    ResetColor
                )?;
                if col < cells.len() - 1 {
                    queue!(
                        w,
                        SetBackgroundColor(bg),
                        SetForegroundColor(Color::White),
                        Print("│"),
                        ResetColor
                    )?;
                }
            }
        }
        self.pending_newline = true;
        self.table_header_printed = true;
        Ok(())
    }

    pub fn render_inline(&mut self, text: &str, def_bg: Option<Color>, restore_fg: Option<&str>) {
        // Pre-process links
        let text_linked = RE_LINK.replace_all(text, |c: &regex::Captures| {
            format!(
                "\x1b]8;;{}\x1b\\\x1b[33;4m{}\x1b[24;39m\x1b]8;;\x1b\\",
                &c[2], &c[1]
            )
        });

        let mut parts: Vec<InlinePart> = Vec::new();
        let caps_iter = RE_TOKENIZER.captures_iter(&text_linked);
        let tokens_raw: Vec<&str> = caps_iter.map(|c| c.get(1).unwrap().as_str()).collect();

        // Pass 1: Build basic tokens
        for (i, tok) in tokens_raw.iter().enumerate() {
            if self.inline_code_ticks.is_some() {
                if tok.starts_with('`') {
                    if let Some(n) = self.inline_code_ticks {
                        if n == tok.len() {
                            let formatted = self.format_inline_code(def_bg, restore_fg);
                            parts.push(InlinePart::text(formatted));
                            self.inline_code_ticks = None;
                            self.inline_code_buffer.clear();
                        } else {
                            self.inline_code_buffer.push_str(tok);
                        }
                    }
                } else {
                    self.inline_code_buffer.push_str(tok);
                }
                continue;
            }

            if tok.starts_with('`') {
                self.inline_code_ticks = Some(tok.len());
                self.inline_code_buffer.clear();
                continue;
            }

            if tok.starts_with('\\') && tok.len() > 1 {
                parts.push(InlinePart::text(tok[1..].to_string()));
                continue;
            }

            if tok.starts_with('$') && tok.ends_with('$') && tok.len() > 1 {
                parts.push(InlinePart::text(unicodeit::replace(&tok[1..tok.len() - 1])));
                continue;
            }

            if let Some(c) = tok.chars().next()
                && (c == '*' || c == '_' || c == '~')
            {
                let prev_char = if i > 0 {
                    tokens_raw[i - 1].chars().last().unwrap_or(' ')
                } else {
                    ' '
                };
                let next_char = if i + 1 < tokens_raw.len() {
                    tokens_raw[i + 1].chars().next().unwrap_or(' ')
                } else {
                    ' '
                };

                // Inline Flanking Logic (Optimization #3: Lazy Calculation)
                let is_ws_next = next_char.is_whitespace();
                let is_ws_prev = prev_char.is_whitespace();
                let is_punct_next = !next_char.is_alphanumeric() && !is_ws_next;
                let is_punct_prev = !prev_char.is_alphanumeric() && !is_ws_prev;
                let left_flanking =
                    !is_ws_next && (!is_punct_next || (is_ws_prev || is_punct_prev));
                let right_flanking =
                    !is_ws_prev && (!is_punct_prev || (is_ws_next || is_punct_next));

                let (can_open, can_close) = if c == '_' {
                    (
                        left_flanking && (!right_flanking || is_punct_prev),
                        right_flanking && (!left_flanking || is_punct_next),
                    )
                } else {
                    (left_flanking, right_flanking)
                };

                parts.push(InlinePart {
                    content: tok.to_string(),
                    is_delim: true,
                    char: c,
                    len: tok.len(),
                    can_open,
                    can_close,
                    pre_style: vec![],
                    post_style: vec![],
                });
            } else {
                parts.push(InlinePart::text(tok.to_string()));
            }
        }

        // Pass 2: Delimiter Matching (Extracted Logic)
        self.resolve_delimiters(&mut parts);

        // Pass 3: Render
        for part in parts {
            for s in &part.pre_style {
                self.scratch_buffer.push_str(s);
            }
            self.scratch_buffer.push_str(&part.content);
            for s in &part.post_style {
                self.scratch_buffer.push_str(s);
            }
        }
    }

    fn resolve_delimiters(&self, parts: &mut [InlinePart]) {
        let mut stack: Vec<usize> = Vec::new();

        for i in 0..parts.len() {
            if !parts[i].is_delim {
                continue;
            }

            if parts[i].can_close {
                // Iterate stack in reverse
                let mut stack_idx = stack.len();
                while stack_idx > 0 {
                    let open_pos = stack_idx - 1;
                    let open_idx = stack[open_pos];

                    // Check if match is possible
                    if parts[open_idx].char == parts[i].char && parts[open_idx].can_open {
                        // Determine consumption length
                        // Rule 14: Use length 1 first to satisfy Italic-outer (<em><strong>...</strong></em>)
                        // If total length is 3 and we match 3, 1 is preferred as outer.
                        let use_len = if parts[i].len == 3 && parts[open_idx].len == 3 {
                            1
                        } else if parts[i].len >= 2 && parts[open_idx].len >= 2 {
                            2
                        } else {
                            1
                        };

                        let (style_on, style_off) = match (parts[open_idx].char, use_len) {
                            ('~', _) => ("\x1b[9m", "\x1b[29m"),
                            ('_', 1) => ("\x1b[4m", "\x1b[24m"),
                            (_, 1) => ("\x1b[3m", "\x1b[23m"),
                            (_, 2) => ("\x1b[1m", "\x1b[22m"),
                            _ => ("", ""),
                        };

                        let char_str = parts[open_idx].char.to_string();

                        // APPLY STYLES
                        // CommonMark Rule 14 and delimiter pairing logic.
                        // Order of application depends on whether we match inner or outer pairs first.
                        // For openers: post_style is closer to the text (inner).
                        // For closers: pre_style is closer to the text (inner).

                        // Heuristic: Italic (len 1) is outer, Bold (len 2) is inner for ***.
                        if use_len == 1 {
                            // Italic is Outer: Outer edges.
                            parts[open_idx].pre_style.push(style_on.to_string());
                            parts[i].post_style.push(style_off.to_string());
                        } else {
                            // Bold is Inner: Inner edges (near text).
                            parts[open_idx].post_style.push(style_on.to_string());
                            parts[i].pre_style.push(style_off.to_string());
                        }

                        // Consume tokens
                        parts[open_idx].len -= use_len;
                        parts[i].len -= use_len;
                        parts[open_idx].content = char_str.repeat(parts[open_idx].len);
                        parts[i].content = char_str.repeat(parts[i].len);

                        // Stack Management
                        if parts[open_idx].len == 0 {
                            stack.remove(open_pos);
                            // Stack shifted, so current stack_idx is now the *next* item.
                            // Decrementing continues the loop correctly down the stack.
                            stack_idx -= 1;
                        } else {
                            // Opener still has length (e.g. *** matched ** -> * left).
                            // We do NOT decrement stack_idx here, effectively retrying this opener
                            // against the *same* closer (if closer has len) or next iteration.
                            // BUT: Current closer might be exhausted.
                        }

                        if parts[i].len == 0 {
                            break;
                        }
                        // If closer still has length, we continue loop to find another opener?
                        // CommonMark says: "If the closer is not exhausted... continue searching...".
                        // So we continue the while loop.
                    } else {
                        stack_idx -= 1;
                    }
                }
            }

            if parts[i].len > 0 && parts[i].can_open {
                stack.push(i);
            }
        }
    }

    fn push_style(&mut self, active: bool, on: &str, off: &str) {
        self.scratch_buffer.push_str(if active { on } else { off });
    }

    fn format_inline_code(&self, def_bg: Option<Color>, restore_fg: Option<&str>) -> String {
        // Reuse buffer for speed? No, string is small.
        let mut out = String::new();
        let norm = if self.inline_code_buffer.len() >= 2
            && self.inline_code_buffer.starts_with(' ')
            && self.inline_code_buffer.ends_with(' ')
            && !self.inline_code_buffer.trim().is_empty()
        {
            &self.inline_code_buffer[1..self.inline_code_buffer.len() - 1]
        } else {
            &self.inline_code_buffer
        };

        let _ = write!(out, "\x1b[48;2;60;60;60m\x1b[38;2;255;255;255m{}", norm);
        if let Some(Color::Rgb { r, g, b }) = def_bg {
            let _ = write!(out, "\x1b[48;2;{};{};{}m", r, g, b);
        } else {
            out.push_str("\x1b[49m");
        }
        out.push_str(restore_fg.unwrap_or("\x1b[39m"));
        out
    }

    fn start_highlighter(&mut self, lang: &str) {
        let ss = &*SYNTAX_SET;
        let syntax = ss
            .find_syntax_by_token(lang)
            .unwrap_or_else(|| ss.find_syntax_plain_text());
        self.highlighter = Some(HighlightLines::new(syntax, &THEME));
    }
}
