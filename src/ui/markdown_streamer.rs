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
use std::ops::Range;
use std::sync::LazyLock;
use syntect::easy::HighlightLines;
use syntect::highlighting::{Theme, ThemeSet};
use syntect::parsing::SyntaxSet;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

// --- Static Resources ---
static SYNTAX_SET: LazyLock<SyntaxSet> = LazyLock::new(two_face::syntax::extra_no_newlines);
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

// --- UI Styling ---
const STYLE_H1: &str = "\x1b[1m";
const STYLE_H2: &str = "\x1b[1m\x1b[94m";
const STYLE_H3: &str = "\x1b[1m\x1b[36m";
const STYLE_H_DEFAULT: &str = "\x1b[1m\x1b[33m";
const STYLE_INLINE_CODE: &str = "\x1b[48;2;60;60;60m\x1b[38;2;255;255;255m";
const STYLE_BLOCKQUOTE: &str = "\x1b[38;5;240m";
const STYLE_LIST_BULLET: &str = "\x1b[33m";
const STYLE_MATH: &str = "\x1b[36;3m";
const STYLE_RESET: &str = "\x1b[0m";
const STYLE_RESET_BG: &str = "\x1b[49m";
const STYLE_RESET_FG: &str = "\x1b[39m";

const COLOR_CODE_BG: Color = Color::Rgb {
    r: 30,
    g: 30,
    b: 30,
};

// Single pattern for "Invisible" content (ANSI codes + OSC8 links) used for width calculation
static RE_INVISIBLE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!("({}|{})", OSC8_PATTERN, ANSI_REGEX_PATTERN)).unwrap());

// --- ANSI & Links ---
// Shared pattern for OSC 8 links: \x1b]8;; ... \x1b\
const OSC8_PATTERN: &str = r"\x1b]8;;.*?\x1b\\";

// Regex allows up to 2 levels of nested brackets/parentheses
static RE_LINK: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"\[((?:[^\[\]]|\[(?:[^\[\]]|\[[^\[\]]*\])*\])*)\]\(((?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))*)\)",
    )
    .unwrap()
});
static RE_OSC8: LazyLock<Regex> = LazyLock::new(|| Regex::new(OSC8_PATTERN).unwrap());

static RE_AUTOLINK: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"<([a-zA-Z][a-zA-Z0-9+.-]{1,31}:[^<> \x00-\x1f]+)>").unwrap()
});

static RE_OPAQUE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(&format!(
        r"(?x)
        (?P<code>`+) |
        (?P<link>{}) |
        (?P<autolink>{}) |
        (?P<math>\$[^\$\s](?:[^\$\n]*?[^\$\s])?\$ | \$) |
        (?P<escape>\\[\s\S]) |
        (?P<ansi>{}|{}) |
        (?P<delim>~~|~|\*\*\*|___|\*\*|__|\*|_)",
        RE_LINK.as_str(),
        RE_AUTOLINK.as_str(),
        OSC8_PATTERN,
        ANSI_REGEX_PATTERN
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

struct ListLevel {
    source_indent: usize,
    marker_width: usize,
}

impl ListLevel {
    fn new(source_indent: usize, marker_width: usize) -> Self {
        Self {
            source_indent,
            marker_width,
        }
    }
}

struct ListContext {
    levels: Vec<ListLevel>,
}

impl ListContext {
    fn new() -> Self {
        Self { levels: Vec::new() }
    }

    fn is_empty(&self) -> bool {
        self.levels.is_empty()
    }

    fn structural_width(&self) -> usize {
        self.levels.iter().map(|l| l.marker_width).sum()
    }

    fn parent_width(&self) -> usize {
        if self.levels.is_empty() {
            0
        } else {
            self.levels[..self.levels.len() - 1]
                .iter()
                .map(|l| l.marker_width)
                .sum()
        }
    }

    fn last_indent(&self) -> Option<usize> {
        self.levels.last().map(|l| l.source_indent)
    }

    fn push(&mut self, source_indent: usize, marker_width: usize) {
        self.levels
            .push(ListLevel::new(source_indent, marker_width));
    }

    fn pop_to_indent(&mut self, indent: usize) {
        while self.levels.last().is_some_and(|l| l.source_indent > indent) {
            self.levels.pop();
        }
    }

    fn update_last_marker_width(&mut self, marker_width: usize) {
        if let Some(last) = self.levels.last_mut() {
            last.marker_width = marker_width;
        }
    }

    fn clear(&mut self) {
        self.levels.clear();
    }
}

struct InlineCodeState {
    ticks: Option<usize>,
    buffer: String,
}

impl InlineCodeState {
    fn new() -> Self {
        Self {
            ticks: None,
            buffer: String::new(),
        }
    }

    fn is_active(&self) -> bool {
        self.ticks.is_some()
    }

    fn open(&mut self, tick_count: usize) {
        self.ticks = Some(tick_count);
        self.buffer.clear();
    }

    fn push_content(&mut self, content: &str) {
        self.buffer.push_str(&content.replace('\n', " "));
    }

    fn close(&mut self) -> String {
        let result = Self::normalize_content_static(&self.buffer);
        self.ticks = None;
        self.buffer.clear();
        result
    }

    fn append_space(&mut self) {
        if self.is_active() {
            self.buffer.push(' ');
        }
    }

    fn normalize_content_static(s: &str) -> String {
        if s.len() >= 2
            && s.starts_with(' ')
            && s.ends_with(' ')
            && s.chars().any(|c| c != ' ')
        {
            s[1..s.len() - 1].to_string()
        } else {
            s.to_string()
        }
    }

    fn flush_incomplete(&self) -> Option<(usize, String)> {
        self.ticks.map(|n| (n, self.buffer.clone()))
    }

    fn reset(&mut self) {
        self.ticks = None;
        self.buffer.clear();
    }
}

enum InlineToken {
    Text(String),
    Delimiter {
        char: char,
        len: usize,
        can_open: bool,
        can_close: bool,
    },
}

struct InlinePart {
    token: InlineToken,
    pre_style: Vec<String>,
    post_style: Vec<String>,
}

impl InlinePart {
    fn text(content: String) -> Self {
        Self {
            token: InlineToken::Text(content),
            pre_style: vec![],
            post_style: vec![],
        }
    }

    fn delimiter(char: char, len: usize, can_open: bool, can_close: bool) -> Self {
        Self {
            token: InlineToken::Delimiter {
                char,
                len,
                can_open,
                can_close,
            },
            pre_style: vec![],
            post_style: vec![],
        }
    }

    fn content(&self) -> String {
        match &self.token {
            InlineToken::Text(s) => s.clone(),
            InlineToken::Delimiter { char, len, .. } => char.to_string().repeat(*len),
        }
    }

    fn is_delim(&self) -> bool {
        matches!(self.token, InlineToken::Delimiter { .. })
    }

    fn delim_char(&self) -> char {
        match &self.token {
            InlineToken::Delimiter { char, .. } => *char,
            _ => '\0',
        }
    }

    fn delim_len(&self) -> usize {
        match &self.token {
            InlineToken::Delimiter { len, .. } => *len,
            _ => 0,
        }
    }

    fn can_open(&self) -> bool {
        match &self.token {
            InlineToken::Delimiter { can_open, .. } => *can_open,
            _ => false,
        }
    }

    fn can_close(&self) -> bool {
        match &self.token {
            InlineToken::Delimiter { can_close, .. } => *can_close,
            _ => false,
        }
    }

    fn consume(&mut self, amount: usize) {
        if let InlineToken::Delimiter { len, .. } = &mut self.token {
            *len = len.saturating_sub(amount);
        }
    }
}

// --- Block Classification ---

#[derive(Debug, Clone, PartialEq)]
pub enum BlockKind {
    FenceOpen {
        fence_char: char,
        fence_len: usize,
        indent: usize,
        lang: String,
    },
    FenceClose,
    FenceContent,
    MathOpen,
    MathClose,
    MathContent,
    TableSeparator,
    TableRow,
    Header {
        level: usize,
        text: String,
    },
    ThematicBreak,
    ListItem {
        indent: usize,
        marker: String,
        separator: String,
        content: String,
        is_ordered: bool,
    },
    BlankLine,
    Paragraph,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ClassifiedLine {
    pub blockquote_depth: usize,
    pub kind: BlockKind,
}

#[derive(Debug, Clone)]
enum ParsedSegment {
    /// A complete inline code span on a single line (e.g., `foo`).
    CodeSpan {
        range: Range<usize>,
        delimiter_len: usize,
    },
    /// The opening backticks of a multi-line span.
    CodeSpanOpener {
        range: Range<usize>,
        delimiter_len: usize,
    },
    /// Text content inside an active multi-line code span.
    CodeSpanContent(Range<usize>),
    /// The closing backticks of a multi-line span.
    CodeSpanCloser {
        range: Range<usize>,
        delimiter_len: usize,
    },
    Link(Range<usize>),
    Autolink(Range<usize>),
    Math(Range<usize>),
    Escape(Range<usize>),
    Ansi(Range<usize>),
    Delim(Range<usize>),
    Text(Range<usize>),
}

fn find_backtick_closer(text: &str, n: usize) -> Option<usize> {
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'`' {
            let mut count = 0;
            while i + count < bytes.len() && bytes[i + count] == b'`' {
                count += 1;
            }
            if count == n {
                return Some(i);
            }
            i += count;
        } else {
            i += 1;
        }
    }
    None
}

fn parse_segments(text: &str, active_ticks: Option<usize>) -> Vec<ParsedSegment> {

    let mut segments = Vec::new();
    let mut pos = 0;

    // Handle active multi-line code span
    if let Some(n) = active_ticks {
        if let Some(close_idx) = find_backtick_closer(text, n) {
            if close_idx > 0 {
                segments.push(ParsedSegment::CodeSpanContent(pos..close_idx));
            }
            let close_start = close_idx;
            let close_end = close_idx + n;
            segments.push(ParsedSegment::CodeSpanCloser {
                range: close_start..close_end,
                delimiter_len: n,
            });
            pos = close_end;
        } else {
            if !text.is_empty() {
                segments.push(ParsedSegment::CodeSpanContent(pos..text.len()));
            }
            return segments;
        }
    }

    let rest = &text[pos..];
    let offset = pos;
    let mut it = RE_OPAQUE.captures_iter(rest).peekable();
    let mut last_match_end = 0;

    while let Some(caps) = it.next() {
        let m = caps.get(0).unwrap();
        if m.start() > last_match_end {
            segments.push(ParsedSegment::Text(offset + last_match_end..offset + m.start()));
        }

        let start = offset + m.start();
        let mut end = offset + m.end();

        if let Some(code) = caps.name("code") {
            let ticks = code.as_str();
            let n = ticks.len();
            let search_start = m.end();
            if let Some(close_idx) = find_backtick_closer(&rest[search_start..], n) {
                end = offset + search_start + close_idx + n;
                while it
                    .peek()
                    .map_or(false, |next| offset + next.get(0).unwrap().start() < end)
                {
                    it.next();
                }
                segments.push(ParsedSegment::CodeSpan {
                    range: start..end,
                    delimiter_len: n,
                });
                last_match_end = search_start + close_idx + n;
                continue;
            } else {
                segments.push(ParsedSegment::CodeSpanOpener {
                    range: start..end,
                    delimiter_len: n,
                });
                if end < text.len() {
                    segments.push(ParsedSegment::CodeSpanContent(end..text.len()));
                }
                return segments;
            }
        } else if caps.name("link").is_some() {
            segments.push(ParsedSegment::Link(start..end));
        } else if caps.name("autolink").is_some() {
            segments.push(ParsedSegment::Autolink(start..end));
        } else if caps.name("math").is_some() {
            segments.push(ParsedSegment::Math(start..end));
        } else if caps.name("escape").is_some() {
            segments.push(ParsedSegment::Escape(start..end));
        } else if caps.name("ansi").is_some() {
            segments.push(ParsedSegment::Ansi(start..end));
        } else if caps.name("delim").is_some() {
            segments.push(ParsedSegment::Delim(start..end));
        }
        last_match_end = m.end();
    }

    if offset + last_match_end < text.len() {
        segments.push(ParsedSegment::Text(offset + last_match_end..text.len()));
    }
    segments
}

fn split_table_row<'a>(text: &'a str, segments: &[ParsedSegment]) -> Vec<&'a str> {
    let mut cells = Vec::new();
    let mut start = 0;

    for seg in segments {
        if let ParsedSegment::Text(range) = seg {
            for (i, c) in text[range.clone()].char_indices() {
                if c == '|' {
                    cells.push(&text[start..range.start + i]);
                    start = range.start + i + 1;
                }
            }
        }
    }
    cells.push(&text[start..]);
    cells
}

pub struct MarkdownStreamer {
    // Code State
    active_fence: Option<(char, usize, usize)>, // char, min_len, indent
    code_lang: String,

    // Inline Code State
    inline_code: InlineCodeState,

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
    list_context: ListContext,
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
            inline_code: InlineCodeState::new(),
            in_math_block: false,
            math_buffer: String::new(),
            in_table: false,
            table_header_printed: false,
            highlighter: None,
            line_buffer: String::new(),
            margin: 2,
            blockquote_depth: 0,
            list_context: ListContext::new(),
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
        if let Some((ticks, buffer)) = self.inline_code.flush_incomplete() {
            let prefix = "`".repeat(ticks);
            let formatted = self.format_inline_code_content(&format!("{}{}", prefix, buffer), None, None);
            queue!(writer, Print(formatted))?;
            self.inline_code.reset();
        }
        Ok(())
    }

    // --- Pipeline Controller ---
    fn process_line<W: Write>(&mut self, w: &mut W, raw_line: &str) -> io::Result<()> {
        let expanded = self.expand_tabs(raw_line);
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

        let prefix = self.build_block_prefix();

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
                self.list_context.pop_to_indent(indent_len);
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
                    Print(STYLE_MATH),
                    Print(converted),
                    Print(STYLE_RESET)
                )?;
                self.pending_newline = true;
                self.math_buffer.clear();
            } else {
                self.flush_pending_inline(w)?;
                self.commit_newline(w)?;
                self.exit_block_context();
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
                self.exit_block_context();
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
            let text = self.clean_atx_header_text(caps.get(2).map_or("", |m| m.as_str()));
            self.exit_block_context();

            queue!(w, Print(prefix))?;
            if level <= 2 {
                queue!(w, Print("\n"))?;
            }

            self.scratch_buffer.clear();
            let style = match level {
                1 => STYLE_H1,
                2 => STYLE_H2,
                3 => STYLE_H3,
                _ => STYLE_H_DEFAULT,
            };
            self.render_inline(text, None, Some(style));

            if level <= 2 {
                let lines = self.wrap_ansi(&self.scratch_buffer, avail);
                for (i, line) in lines.iter().enumerate() {
                    let pad = avail.saturating_sub(self.visible_width(line)) / 2;
                    if i > 0 {
                        queue!(w, Print("\n"), Print(prefix))?;
                    }
                    queue!(
                        w,
                        Print(" ".repeat(pad)),
                        Print(format!("{}{}{}", style, line, STYLE_RESET)),
                        ResetColor
                    )?;
                }
                if level == 1 {
                    queue!(w, Print("\n"), Print(prefix), Print("─".repeat(avail)))?;
                }
                self.pending_newline = true;
            } else {
                queue!(
                    w,
                    Print(style),
                    Print(&self.scratch_buffer),
                    Print(STYLE_RESET)
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

            let last_indent = self.list_context.last_indent().unwrap_or(0);
            if self.list_context.is_empty() || indent > last_indent {
                self.list_context.push(indent, marker_width);
            } else if indent < last_indent {
                self.list_context.pop_to_indent(indent);
                if self.list_context.last_indent().is_some_and(|d| d != indent) {
                    self.list_context.push(indent, marker_width);
                }
            } else {
                // Same level: update width in case marker size changed (e.g. 9. -> 10.)
                self.list_context.update_last_marker_width(marker_width);
            }

            let full_stack_width = self.list_context.structural_width();
            let parent_width = self.list_context.parent_width();

            let hang_indent = " ".repeat(full_stack_width);
            let content_width = avail.saturating_sub(full_stack_width);

            queue!(
                w,
                Print(prefix),
                Print(" ".repeat(parent_width)),
                Print(STYLE_LIST_BULLET),
                Print(disp_bullet),
                Print(STYLE_RESET),
                Print(separator)
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
            self.exit_block_context();
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
            self.exit_block_context();
            if self.blockquote_depth > 0 {
                queue!(w, Print(prefix))?;
            }
            self.pending_newline = true;
            return Ok(());
        }

        if !line_content.is_empty() || self.inline_code.is_active() {
            let mut eff_prefix = self.build_block_prefix();
            if !self.list_context.is_empty() {
                let current_indent = line_content.chars().take_while(|c| *c == ' ').count();
                if current_indent == 0 {
                    self.list_context.clear();
                } else {
                    self.list_context.pop_to_indent(current_indent);
                }

                if !self.list_context.is_empty() {
                    let structural_indent = self.list_context.structural_width();
                    eff_prefix.push_str(&" ".repeat(structural_indent));

                    // To avoid double-indenting, we skip the source indentation that matches
                    // the structural indentation we just applied via eff_prefix.
                    let skip = current_indent.min(structural_indent);
                    line_content = &line_content[skip..];
                }
            }

            self.scratch_buffer.clear();
            if self.inline_code.is_active() {
                self.inline_code.append_space();
            }
            self.render_inline(line_content, None, None);

            let lines = self.wrap_ansi(&self.scratch_buffer, avail);
            let has_visible_content = self.visible_width(&self.scratch_buffer) > 0;
            
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
            if !lines.is_empty() && has_visible_content {
                self.pending_newline = true;
            }
        }
        Ok(())
    }

    fn exit_block_context(&mut self) {
        self.list_context.clear();
        self.in_table = false;
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
                            let c_w = c.width().unwrap_or(0);
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
                        }

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

        // Strip the fence's indentation from the content line (Spec §4.5)
        let skip = raw_line
            .chars()
            .take(fence_indent)
            .take_while(|&c| c == ' ')
            .count();
        let line_content = &raw_line[skip..];

        let mut prefix = " ".repeat(self.margin);
        if !self.list_context.is_empty() {
            let indent_width = self.list_context.structural_width();
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

        // 2. Determine if we need to wrap
        let content_width = self.visible_width(line_content);

        if content_width <= avail_width {
            // Fits in one line: Print directly
            let pad = avail_width.saturating_sub(content_width);
            queue!(
                w,
                Print(&prefix),
                SetBackgroundColor(COLOR_CODE_BG),
                Print(&self.scratch_buffer),
                Print(" ".repeat(pad)),
                ResetColor
            )?;
        } else {
            // Needs wrapping
            let wrapped_lines = self.wrap_ansi(&self.scratch_buffer, avail_width);

            if wrapped_lines.is_empty() {
                queue!(
                    w,
                    Print(&prefix),
                    SetBackgroundColor(COLOR_CODE_BG),
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
                        SetBackgroundColor(COLOR_CODE_BG),
                        Print(line),
                        Print(" ".repeat(pad)),
                        ResetColor
                    )?;
                }
            }
        }
        self.pending_newline = true;
        Ok(())
    }

    fn render_stream_table_row<W: Write>(&mut self, w: &mut W, row_str: &str) -> io::Result<()> {
        self.commit_newline(w)?;
        let term_width = self.get_width();

        let trimmed_row = row_str.trim().trim_matches('|');
        let segments = parse_segments(trimmed_row, None);
        let cells = split_table_row(trimmed_row, &segments);

        if cells.is_empty() {
            return Ok(());
        }

        let prefix_width = self.margin + (self.blockquote_depth * 2);
        let cell_overhead = (cells.len() * 3).saturating_sub(1);
        let avail = term_width.saturating_sub(prefix_width + self.margin + cell_overhead);
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
            COLOR_CODE_BG
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

        let prefix = self.build_block_prefix();

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
        let mut parts = self.build_inline_parts(text, def_bg, restore_fg);
        self.resolve_delimiters(&mut parts);

        for part in parts {
            for s in &part.pre_style {
                self.scratch_buffer.push_str(s);
            }
            self.scratch_buffer.push_str(&part.content());
            for s in &part.post_style {
                self.scratch_buffer.push_str(s);
            }
        }
    }

    fn build_inline_parts(
        &mut self,
        text: &str,
        def_bg: Option<Color>,
        restore_fg: Option<&str>,
    ) -> Vec<InlinePart> {
        let active_ticks = self.inline_code.ticks;
        let segments = parse_segments(text, active_ticks);
        let mut parts: Vec<InlinePart> = Vec::new();

        for seg in &segments {
            match seg {
                ParsedSegment::CodeSpan { range, delimiter_len } => {
                    let n = *delimiter_len;
                    let content_range = range.start + n..range.end - n;
                    let raw_content = &text[content_range];
                    let normalized = InlineCodeState::normalize_content_static(raw_content);
                    let formatted = self.format_inline_code_content(&normalized, def_bg, restore_fg);
                    parts.push(InlinePart::text(formatted));
                }
                ParsedSegment::CodeSpanOpener { range: _, delimiter_len } => {
                    self.inline_code.open(*delimiter_len);
                }
                ParsedSegment::CodeSpanContent(range) => {
                    self.inline_code.push_content(&text[range.clone()]);
                }
                ParsedSegment::CodeSpanCloser { range: _, delimiter_len: _ } => {
                    let content = self.inline_code.close();
                    let formatted =
                        self.format_inline_code_content(&content, def_bg, restore_fg);
                    parts.push(InlinePart::text(formatted));
                }
                ParsedSegment::Escape(r) => {
                    parts.push(InlinePart::text(text[r.start + 1..r.end].to_string()));
                }
                ParsedSegment::Math(r) => {
                    let tok = &text[r.clone()];
                    if tok.len() > 1 && tok.starts_with('$') && tok.ends_with('$') {
                        parts.push(InlinePart::text(unicodeit::replace(&tok[1..tok.len() - 1])));
                    } else {
                        parts.push(InlinePart::text(tok.to_string()));
                    }
                }
                ParsedSegment::Autolink(r) => {
                    let url = &text[r.start + 1..r.end - 1];
                    parts.push(InlinePart::text(format!(
                        "\x1b]8;;{}\x1b\\{}\x1b]8;;\x1b\\",
                        url, url
                    )));
                }
                ParsedSegment::Link(r) => {
                    if let Some(caps) = RE_LINK.captures(&text[r.clone()]) {
                        let link_text = caps.get(1).map_or("", |m| m.as_str());
                        let url = caps.get(2).map_or("", |m| m.as_str());
                        parts.push(InlinePart::text(format!(
                            "\x1b]8;;{}\x1b\\\x1b[33;4m{}\x1b[24;39m\x1b]8;;\x1b\\",
                            url, link_text
                        )));
                    }
                }
                ParsedSegment::Ansi(r) => {
                    parts.push(InlinePart::text(text[r.clone()].to_string()));
                }
                ParsedSegment::Delim(r) => {
                    let tok = &text[r.clone()];
                    let c = tok.chars().next().unwrap();

                    let prev_char = if r.start > 0 {
                        text[..r.start].chars().last().unwrap_or(' ')
                    } else {
                        ' '
                    };
                    let next_char = text[r.end..].chars().next().unwrap_or(' ');

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

                    parts.push(InlinePart::delimiter(c, tok.len(), can_open, can_close));
                }
                ParsedSegment::Text(r) => {
                    parts.push(InlinePart::text(text[r.clone()].to_string()));
                }
            }
        }

        parts
    }

    fn resolve_delimiters(&self, parts: &mut [InlinePart]) {
        let mut stack: Vec<usize> = Vec::new();

        for i in 0..parts.len() {
            if !parts[i].is_delim() {
                continue;
            }

            if parts[i].can_close() {
                let mut stack_idx = stack.len();
                while stack_idx > 0 {
                    let open_pos = stack_idx - 1;
                    let open_idx = stack[open_pos];

                    if parts[open_idx].delim_char() == parts[i].delim_char()
                        && parts[open_idx].can_open()
                    {
                        // Rule 9/10: Multiple of 3 Rule
                        if (parts[open_idx].can_open() && parts[open_idx].can_close())
                            || (parts[i].can_open() && parts[i].can_close())
                        {
                            let sum = parts[open_idx].delim_len() + parts[i].delim_len();
                            if sum.is_multiple_of(3)
                                && (!parts[open_idx].delim_len().is_multiple_of(3)
                                    || !parts[i].delim_len().is_multiple_of(3))
                            {
                                stack_idx -= 1;
                                continue;
                            }
                        }

                        // Empty emphasis check
                        if open_idx + 1 == i {
                            stack_idx -= 1;
                            continue;
                        }

                        // Determine consumption length
                        let open_len = parts[open_idx].delim_len();
                        let close_len = parts[i].delim_len();
                        let use_len = if close_len == 3 && open_len == 3 {
                            1
                        } else if close_len >= 2 && open_len >= 2 {
                            2
                        } else {
                            1
                        };

                        let (style_on, style_off) = match (parts[open_idx].delim_char(), use_len) {
                            ('~', _) => ("\x1b[9m", "\x1b[29m"),
                            ('_', 1) => ("\x1b[4m", "\x1b[24m"),
                            (_, 1) => ("\x1b[3m", "\x1b[23m"),
                            (_, 2) => ("\x1b[1m", "\x1b[22m"),
                            _ => ("", ""),
                        };

                        // Apply styles
                        if use_len == 1 {
                            parts[open_idx].pre_style.push(style_on.to_string());
                            parts[i].post_style.push(style_off.to_string());
                        } else {
                            parts[open_idx].post_style.push(style_on.to_string());
                            parts[i].pre_style.push(style_off.to_string());
                        }

                        // Consume tokens
                        parts[open_idx].consume(use_len);
                        parts[i].consume(use_len);

                        // Stack Management
                        if parts[open_idx].delim_len() == 0 {
                            stack.remove(open_pos);
                            stack_idx -= 1;
                        }

                        if parts[i].delim_len() == 0 {
                            break;
                        }
                    } else {
                        stack_idx -= 1;
                    }
                }
            }

            if parts[i].delim_len() > 0 && parts[i].can_open() {
                stack.push(i);
            }
        }
    }

    fn build_block_prefix(&self) -> String {
        let mut prefix = " ".repeat(self.margin);
        if self.blockquote_depth > 0 {
            prefix.push_str(STYLE_BLOCKQUOTE);
            for _ in 0..self.blockquote_depth {
                prefix.push_str("│ ");
            }
            prefix.push_str(STYLE_RESET);
        }
        prefix
    }

    fn format_inline_code_content(
        &self,
        content: &str,
        def_bg: Option<Color>,
        restore_fg: Option<&str>,
    ) -> String {
        let mut out = String::new();
        let _ = write!(out, "{}{}", STYLE_INLINE_CODE, content);
        if let Some(Color::Rgb { r, g, b }) = def_bg {
            let _ = write!(out, "\x1b[48;2;{};{};{}m", r, g, b);
        } else {
            out.push_str(STYLE_RESET_BG);
        }
        out.push_str(restore_fg.unwrap_or(STYLE_RESET_FG));
        out
    }

    fn expand_tabs(&self, line: &str) -> String {
        let mut expanded = String::with_capacity(line.len());
        let mut col = 0;
        for c in line.chars() {
            if c == '\t' {
                let n = 4 - (col % 4);
                expanded.push_str(&" ".repeat(n));
                col += n;
            } else {
                expanded.push(c);
                col += UnicodeWidthChar::width(c).unwrap_or(0);
            }
        }
        expanded
    }

    pub fn classify_line(&self, expanded: &str) -> ClassifiedLine {
        let trimmed = expanded.trim_end();

        // 1. Continuation contexts (checked before blockquote stripping)

        // Active code fence: check for close or treat as content
        if let Some((f_char, min_len, _indent)) = self.active_fence {
            if let Some(caps) = RE_CODE_FENCE.captures(trimmed) {
                let fence = &caps[2];
                if fence.starts_with(f_char) && fence.len() >= min_len && caps[3].trim().is_empty()
                {
                    return ClassifiedLine {
                        blockquote_depth: 0,
                        kind: BlockKind::FenceClose,
                    };
                }
            }
            return ClassifiedLine {
                blockquote_depth: 0,
                kind: BlockKind::FenceContent,
            };
        }

        // Active math block
        if self.in_math_block {
            if RE_MATH_BLOCK.is_match(trimmed) {
                return ClassifiedLine {
                    blockquote_depth: 0,
                    kind: BlockKind::MathClose,
                };
            }
            return ClassifiedLine {
                blockquote_depth: 0,
                kind: BlockKind::MathContent,
            };
        }

        // Table separator (only when already in a table)
        if self.in_table && RE_TABLE_SEP.is_match(trimmed) {
            return ClassifiedLine {
                blockquote_depth: 0,
                kind: BlockKind::TableSeparator,
            };
        }

        // Table row (before blockquote stripping, matching current precedence)
        if RE_TABLE_ROW.is_match(trimmed) {
            return ClassifiedLine {
                blockquote_depth: 0,
                kind: BlockKind::TableRow,
            };
        }

        // 2. Strip blockquotes and count depth
        let mut content = expanded.to_string();
        let mut blockquote_depth = 0;
        loop {
            let trimmed_content = content.clone();
            if let Some(caps) = RE_BLOCKQUOTE.captures(&trimmed_content) {
                blockquote_depth += 1;
                content = caps.get(2).map_or("", |m| m.as_str()).to_string();
            } else {
                break;
            }
        }

        let clean = content.trim_end();

        // 3. Post-blockquote classification

        // Code fence open
        if let Some(caps) = RE_CODE_FENCE.captures(clean) {
            let fence = &caps[2];
            let indent_len = caps[1].len();
            let info = caps[3].trim();
            if let Some(f_char) = fence.chars().next() {
                if f_char != '`' || !info.contains('`') {
                    let lang = info
                        .split_whitespace()
                        .next()
                        .unwrap_or("bash")
                        .to_string();
                    return ClassifiedLine {
                        blockquote_depth,
                        kind: BlockKind::FenceOpen {
                            fence_char: f_char,
                            fence_len: fence.len(),
                            indent: indent_len,
                            lang,
                        },
                    };
                }
            }
        }

        // Math block open
        if RE_MATH_BLOCK.is_match(clean) {
            return ClassifiedLine {
                blockquote_depth,
                kind: BlockKind::MathOpen,
            };
        }

        // Header
        if let Some(caps) = RE_HEADER.captures(clean) {
            let level = caps.get(1).map_or(0, |m| m.len());
            let raw_text = caps.get(2).map_or("", |m| m.as_str());
            let text = Self::clean_atx_header_text_static(raw_text).to_string();
            return ClassifiedLine {
                blockquote_depth,
                kind: BlockKind::Header { level, text },
            };
        }

        // Thematic break (must be checked before list to handle `* * *`)
        if RE_HR.is_match(clean) {
            return ClassifiedLine {
                blockquote_depth,
                kind: BlockKind::ThematicBreak,
            };
        }

        // List item
        if let Some(caps) = RE_LIST.captures(clean) {
            let indent = caps.get(1).map_or(0, |m| m.len());
            let marker = caps.get(2).map_or("", |m| m.as_str()).to_string();
            let separator = caps.get(3).map_or(" ", |m| m.as_str()).to_string();
            let content_text = caps.get(4).map_or("", |m| m.as_str()).to_string();
            let is_ordered = marker.chars().any(|c| c.is_numeric());
            return ClassifiedLine {
                blockquote_depth,
                kind: BlockKind::ListItem {
                    indent,
                    marker,
                    separator,
                    content: content_text,
                    is_ordered,
                },
            };
        }

        // Blank line
        if clean.is_empty() {
            return ClassifiedLine {
                blockquote_depth,
                kind: BlockKind::BlankLine,
            };
        }

        // Paragraph (fallback)
        ClassifiedLine {
            blockquote_depth,
            kind: BlockKind::Paragraph,
        }
    }

    fn clean_atx_header_text_static(text: &str) -> &str {
        let mut end = text.len();
        let bytes = text.as_bytes();
        while end > 0 && bytes[end - 1] == b'#' {
            end -= 1;
        }
        if end > 0 && end < text.len() && bytes[end - 1] == b' ' {
            &text[..end - 1]
        } else if end == 0 {
            ""
        } else {
            &text[..end]
        }
    }

    fn clean_atx_header_text<'a>(&self, text: &'a str) -> &'a str {
        Self::clean_atx_header_text_static(text)
    }

    fn start_highlighter(&mut self, lang: &str) {
        let ss = &*SYNTAX_SET;
        let syntax = ss
            .find_syntax_by_token(lang)
            .unwrap_or_else(|| ss.find_syntax_plain_text());
        self.highlighter = Some(HighlightLines::new(syntax, &THEME));
    }
}
