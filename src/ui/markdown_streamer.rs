// This implementation is loosly based on https://github.com/day50-dev/Streamdown
use crate::console::ANSI_REGEX_PATTERN;
use crossterm::{
    queue,
    style::{
        Attribute, Color, Print, ResetColor, SetAttribute, SetBackgroundColor, SetForegroundColor,
    },
};
use regex::Regex;
use std::io::{self, Write};
use std::sync::OnceLock;
use syntect::easy::HighlightLines;
use syntect::highlighting::{Theme, ThemeSet};
use syntect::parsing::SyntaxSet;
use unicode_width::UnicodeWidthStr;

// --- Static Resources ---
static SYNTAX_SET: OnceLock<SyntaxSet> = OnceLock::new();
static THEME: OnceLock<Theme> = OnceLock::new();

// Regexes
static RE_CODE_FENCE: OnceLock<Regex> = OnceLock::new();
static RE_HEADER: OnceLock<Regex> = OnceLock::new();
static RE_HR: OnceLock<Regex> = OnceLock::new();
static RE_LIST: OnceLock<Regex> = OnceLock::new();
static RE_BLOCKQUOTE: OnceLock<Regex> = OnceLock::new();
static RE_TABLE_ROW: OnceLock<Regex> = OnceLock::new();
static RE_TABLE_SEP: OnceLock<Regex> = OnceLock::new();
// Math Regexes
static RE_MATH_BLOCK: OnceLock<Regex> = OnceLock::new();

// Tokenizer & Helpers
static RE_TOKENIZER: OnceLock<Regex> = OnceLock::new();
static RE_LINK: OnceLock<Regex> = OnceLock::new();
static RE_ANSI: OnceLock<Regex> = OnceLock::new();
static RE_SPLIT_ANSI: OnceLock<Regex> = OnceLock::new();
static RE_ANSI_PARTS: OnceLock<Regex> = OnceLock::new();

fn get_re(re: &'static OnceLock<Regex>) -> &'static Regex {
    re.get().expect("Regex not initialized")
}

fn init_statics() {
    SYNTAX_SET.get_or_init(SyntaxSet::load_defaults_newlines);
    THEME.get_or_init(|| {
        let ts = ThemeSet::load_defaults();
        ts.themes
            .get("base16-ocean.dark")
            .or_else(|| ts.themes.values().next())
            .expect("No themes found")
            .clone()
    });

    RE_CODE_FENCE.get_or_init(|| Regex::new(r"^(\s*)`{3,5}(\w*)\s*$").unwrap());
    RE_HEADER.get_or_init(|| Regex::new(r"^(#{1,6})\s+(.*)").unwrap());
    RE_HR.get_or_init(|| Regex::new(r"^(\s*[-*_]){3,}\s*$").unwrap());
    RE_LIST.get_or_init(|| Regex::new(r"^(\s*)([-*+]|\d+\.)\s+(.*)").unwrap());
    // Matches ONE level of blockquote: " > " or ">"
    RE_BLOCKQUOTE.get_or_init(|| Regex::new(r"^(\s*>\s?)(.*)").unwrap());

    // Table Regexes
    RE_TABLE_ROW.get_or_init(|| Regex::new(r"^\s*\|(.*)\|\s*$").unwrap());
    RE_TABLE_SEP.get_or_init(|| Regex::new(r"^[\s\|\-\:]+$").unwrap());

    // Math Regexes
    RE_MATH_BLOCK.get_or_init(|| Regex::new(r"^\s*\$\$\s*$").unwrap());

    RE_TOKENIZER.get_or_init(|| {
        Regex::new(r"(\$[^\$\s](?:[^\$\n]*?[^\$\s])?\$|~~|\*\*\*|___|\*\*|__|\*|_|`+|\$|[^~*_`$]+)")
            .unwrap()
    });

    RE_LINK.get_or_init(|| Regex::new(r"\[([^\]]+)\]\(([^\)]+)\)").unwrap());
    RE_ANSI.get_or_init(|| Regex::new(ANSI_REGEX_PATTERN).unwrap());

    // Splits text into: ANSI codes, Spaces, or Words (non-space non-ansi)
    RE_SPLIT_ANSI.get_or_init(|| {
        let pattern = format!("({}|\\s+|[^\\s\\x1b]+)", ANSI_REGEX_PATTERN);
        Regex::new(&pattern).unwrap()
    });
    // Parsing helper for ANSI state tracking
    RE_ANSI_PARTS.get_or_init(|| Regex::new(r"\x1b\[([0-9;]*)m").unwrap());
}

pub struct MarkdownStreamer {
    // Code State
    in_code_block: bool,
    code_lang: String,

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
    list_stack: Vec<(usize, bool, usize)>, // (indent_len, is_ordered, counter)

    // Configuration
    manual_width: Option<usize>,
}

// Theme Constants
const COL_TABLE_HEAD: Color = Color::Rgb {
    r: 60,
    g: 60,
    b: 80,
};
const COL_TABLE_BODY: Color = Color::Rgb {
    r: 30,
    g: 30,
    b: 30,
};
const COL_CODE_BG: Color = Color::Rgb {
    r: 30,
    g: 30,
    b: 30,
};

impl Default for MarkdownStreamer {
    fn default() -> Self {
        Self::new()
    }
}

impl MarkdownStreamer {
    pub fn new() -> Self {
        init_statics();
        Self {
            in_code_block: false,
            code_lang: "bash".to_string(),
            in_math_block: false,
            math_buffer: String::new(),
            in_table: false,
            table_header_printed: false,
            highlighter: None,
            line_buffer: String::new(),
            margin: 2,
            blockquote_depth: 0,
            list_stack: Vec::new(),
            manual_width: None,
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
        if let Some(w) = self.manual_width {
            w
        } else {
            crate::console::get_terminal_width()
        }
    }

    fn visible_width(&self, text: &str) -> usize {
        let stripped = get_re(&RE_ANSI).replace_all(text, "");
        UnicodeWidthStr::width(stripped.as_ref())
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
        writer.flush()
    }

    fn process_line<W: Write>(&mut self, w: &mut W, raw_line: &str) -> io::Result<()> {
        let term_width = self.get_width();

        // Parity: Expand tabs to 2 spaces before processing.
        // This prevents alignment issues in code/tables/wrapping.
        let expanded = raw_line.replace('\t', "  ");
        let trimmed = expanded.trim_end();

        // --- 1. CODE BLOCK HANDLING ---
        if let Some(caps) = get_re(&RE_CODE_FENCE).captures(trimmed) {
            if self.in_code_block {
                self.in_code_block = false;
                queue!(w, ResetColor, Print("\n"))?;
            } else {
                self.in_code_block = true;
                self.list_stack.clear();
                let lang = caps.get(2).map_or("bash", |m| m.as_str());
                self.code_lang = if lang.is_empty() {
                    "bash".to_string()
                } else {
                    lang.to_string()
                };
                self.start_highlighter(&self.code_lang.clone());
            }
            return Ok(());
        }

        if self.in_code_block {
            return self.render_code_line(w, &expanded);
        }

        // --- 1.5. MATH BLOCK HANDLING ---
        // Check for block toggle '$$'
        if get_re(&RE_MATH_BLOCK).is_match(trimmed) {
            if self.in_math_block {
                // Closing Math Block
                self.in_math_block = false;

                // Convert LaTeX to Unicode
                let converted = unicodeit::replace(&self.math_buffer);

                // Style: Centered, Italic, Cyan (Math look)
                // Calculate Layout
                let prefix = " ".repeat(self.margin);
                let prefix_width = self.margin + (self.blockquote_depth * 2);
                let right_margin = self.margin;
                let available_width = term_width.saturating_sub(prefix_width + right_margin);

                let vis_len = self.visible_width(&converted);
                let padding = available_width.saturating_sub(vis_len) / 2;

                queue!(w, Print(&prefix), Print(" ".repeat(padding)))?;
                queue!(
                    w,
                    SetForegroundColor(Color::Cyan),
                    SetAttribute(Attribute::Italic),
                    Print(converted),
                    ResetColor,
                    SetAttribute(Attribute::Reset),
                    Print("\n")
                )?;

                self.math_buffer.clear();
            } else {
                // Opening Math Block
                self.list_stack.clear();
                self.in_math_block = true;
            }
            return Ok(());
        }

        if self.in_math_block {
            self.math_buffer.push_str(trimmed);
            self.math_buffer.push(' '); // join lines with space
            return Ok(());
        }

        // --- 2. TABLE HANDLING ---
        // Detect Separator Row
        if self.in_table && get_re(&RE_TABLE_SEP).is_match(trimmed) {
            self.table_header_printed = true;
            return Ok(());
        }

        if get_re(&RE_TABLE_ROW).is_match(trimmed) {
            self.in_table = true;
            self.list_stack.clear();
            return self.render_stream_table_row(w, trimmed);
        } else if self.in_table {
            self.in_table = false;
            self.table_header_printed = false;
        }

        // --- 3. BLOCKQUOTE & PREFIX CALCULATION ---
        let mut content = raw_line;
        let mut line_depth = 0;
        let re_bq = get_re(&RE_BLOCKQUOTE);

        while let Some(caps) = re_bq.captures(content) {
            line_depth += 1;
            if let Some(m) = caps.get(2) {
                content = m.as_str();
            } else {
                break;
            }
        }

        // Strict state reset matching Python
        self.blockquote_depth = line_depth;

        let mut prefix = " ".repeat(self.margin);
        if self.blockquote_depth > 0 {
            prefix.push_str("\x1b[38;5;240m"); // ANSI Grey
            for _ in 0..self.blockquote_depth {
                prefix.push_str("│ ");
            }
            prefix.push_str("\x1b[0m");
        }

        // Layout Geometry
        let prefix_width = self.margin + (self.blockquote_depth * 2);
        let right_margin = self.margin;
        let available_width = term_width.saturating_sub(prefix_width + right_margin);

        let clean_content = content.trim_end();

        // --- 4. HEADER HANDLING ---
        if let Some(caps) = get_re(&RE_HEADER).captures(clean_content) {
            let level_str = caps.get(1).map_or("", |m| m.as_str());
            let text = caps.get(2).map_or("", |m| m.as_str());
            let level = level_str.len();
            self.list_stack.clear();

            match level {
                1 => {
                    queue!(w, Print(&prefix), Print("\n"))?;

                    let styled_text = self.render_inline_to_string(text, None, Some("\x1b[1m"));
                    let lines = self.wrap_ansi(&styled_text, available_width);

                    for line in lines {
                        let text_len = self.visible_width(&line);
                        let padding = available_width.saturating_sub(text_len) / 2;
                        queue!(
                            w,
                            Print(&prefix),
                            Print(" ".repeat(padding)),
                            Print(format!("\x1b[1m{}\x1b[0m", line)),
                            ResetColor,
                            SetAttribute(Attribute::Reset),
                            Print("\n")
                        )?;
                    }
                    return Ok(());
                }
                2 => {
                    queue!(w, Print(&prefix), Print("\n"))?;

                    let styled_text = self.render_inline_to_string(text, None, Some("\x1b[1;94m"));
                    let lines = self.wrap_ansi(&styled_text, available_width);

                    for line in lines {
                        let text_len = self.visible_width(&line);
                        let padding = available_width.saturating_sub(text_len) / 2;
                        queue!(
                            w,
                            Print(&prefix),
                            Print(" ".repeat(padding)),
                            Print(format!("\x1b[1;94m{}\x1b[0m", line)),
                            ResetColor,
                            SetAttribute(Attribute::Reset),
                            Print("\n")
                        )?;
                    }
                    return Ok(());
                }
                _ => {}
            }

            let (style_str, styled_text) = match level {
                3 => (
                    "\x1b[1;36m",
                    self.render_inline_to_string(text, None, Some("\x1b[1;36m")),
                ),
                _ => (
                    "\x1b[1;33m",
                    self.render_inline_to_string(text, None, Some("\x1b[1;33m")),
                ),
            };

            queue!(w, Print(&prefix))?;
            queue!(w, Print(style_str), Print(styled_text), Print("\x1b[0m\n"))?;
            return Ok(());
        }

        // --- 5. LIST HANDLING ---
        if let Some(caps) = get_re(&RE_LIST).captures(clean_content) {
            let raw_indent = caps.get(1).map_or("", |m| m.as_str());
            let bullet = caps.get(2).map_or("-", |m| m.as_str());
            let text_part = caps.get(3).map_or("", |m| m.as_str());

            let indent_len = raw_indent.len();
            let is_ordered = bullet.chars().any(|c| c.is_numeric());

            // --- Stack Logic (Simplified for Indentation Only) ---
            // We only need the stack to track nesting levels for the visual tree/margin.
            let last_indent = self.list_stack.last().map(|(len, _, _)| *len).unwrap_or(0);

            if self.list_stack.is_empty() || indent_len > last_indent {
                self.list_stack.push((indent_len, is_ordered, 0)); // 0 is dummy counter
            } else if indent_len < last_indent {
                while self
                    .list_stack
                    .last()
                    .is_some_and(|(d, _, _)| *d > indent_len)
                {
                    self.list_stack.pop();
                }
                // If we popped everything or landed on a mismatch, push new level
                let should_push = match self.list_stack.last() {
                    Some((d, _, _)) => *d != indent_len,
                    None => true,
                };
                if should_push {
                    self.list_stack.push((indent_len, is_ordered, 0));
                }
            }

            // --- Display Logic ---
            // Use the raw captured bullet. If it was "2.", print "2.".
            // If it was unordered ("-", "*", "+"), normalize to "•".
            let display_bullet = if is_ordered {
                bullet.to_string()
            } else {
                "•".to_string() // Normalize '-', '*', '+' to a nice dot
            };
            let display_bullet = &display_bullet;

            let nesting_level = self.list_stack.len().saturating_sub(1);
            let normalized_indent = " ".repeat(nesting_level * 2);
            let bullet_vis_width = self.visible_width(display_bullet) + 1;
            let hang_indent_str = " ".repeat((nesting_level * 2) + bullet_vis_width);

            // 1. Render Styles First
            let styled_text = self.render_inline_to_string(text_part, None, None);

            // 2. Wrap using ANSI-aware logic. We wrap the content only, manually prepending and bullets/indent.
            let content_width = available_width.saturating_sub(hang_indent_str.len());
            let lines = self.wrap_ansi(&styled_text, content_width);

            // Print Line 1: Manually print Prefix + Normalized Indent + Display Bullet
            queue!(
                w,
                Print(&prefix),
                Print(&normalized_indent),
                SetForegroundColor(Color::Yellow),
                Print(display_bullet),
                Print(" "),
                ResetColor
            )?;

            if let Some(first) = lines.first() {
                queue!(w, Print(first), ResetColor, SetAttribute(Attribute::Reset))?;
            }
            queue!(w, Print("\n"))?;

            // Print Subsequent Lines
            for line in lines.iter().skip(1) {
                queue!(w, Print(&prefix))?;
                queue!(w, Print(&hang_indent_str))?;
                queue!(w, Print(line))?;
                queue!(w, ResetColor, SetAttribute(Attribute::Reset), Print("\n"))?;
            }
            return Ok(());
        }

        // --- 6. HORIZONTAL RULE ---
        if get_re(&RE_HR).is_match(clean_content) {
            queue!(
                w,
                Print(&prefix),
                SetForegroundColor(Color::DarkGrey),
                Print("─".repeat(available_width)),
                ResetColor,
                Print("\n")
            )?;
            self.list_stack.clear();
            return Ok(());
        }

        // --- 7. STANDARD TEXT ---
        if clean_content.is_empty() {
            if self.blockquote_depth > 0 {
                queue!(w, Print(&prefix), Print("\n"))?;
            } else {
                queue!(w, Print("\n"))?;
            }
        } else {
            // Apply inline formatting FIRST, then wrap preserving ANSI
            let styled_text = self.render_inline_to_string(clean_content, None, None);
            let lines = self.wrap_ansi(&styled_text, available_width);

            for line in lines {
                queue!(w, ResetColor, SetAttribute(Attribute::Reset))?;
                queue!(w, Print(&prefix))?;
                queue!(w, Print(&line))?;
                queue!(w, ResetColor, SetAttribute(Attribute::Reset))?;
                queue!(w, Print("\n"))?;
            }
        }
        Ok(())
    }

    // --- ANSI Aware Wrapping ---
    fn wrap_ansi(&self, text: &str, width: usize) -> Vec<String> {
        let mut lines = Vec::new();
        let mut current_line = String::new();
        let mut current_len = 0;

        // Active ANSI codes stack (to avoid bloat)
        let mut active_codes: Vec<String> = Vec::new();

        for caps in get_re(&RE_SPLIT_ANSI).captures_iter(text) {
            let token = caps.get(1).unwrap().as_str();

            if token.starts_with("\x1b") {
                current_line.push_str(token);
                self.update_ansi_state(&mut active_codes, token);
            } else {
                let mut token_str = token;
                let mut token_len = UnicodeWidthStr::width(token_str);

                while current_len + token_len > width && width > 0 {
                    // If the token itself is longer than the width and we are at start of line,
                    // we must hard-wrap the token.
                    if current_len == 0 {
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

                        // Force split at least one char if zero (shouldn't happen with width > 0)
                        if split_idx == 0 {
                            split_idx = token_str.chars().next().map_or(0, |c| c.len_utf8());
                        }

                        // If it's still 0, it means the string was empty, so we break to avoid infinite loop
                        if split_idx == 0 {
                            break;
                        }

                        let head = &token_str[..split_idx];
                        current_line.push_str(head);
                        lines.push(current_line);

                        current_line = active_codes.join("");
                        token_str = &token_str[split_idx..];
                        token_len = UnicodeWidthStr::width(token_str);
                        current_len = 0;
                    } else {
                        // Move to next line if not a lone space
                        if !token_str.trim().is_empty() {
                            lines.push(current_line);
                            current_line = active_codes.join("");
                            current_len = 0;
                        } else {
                            // Swallow trailing whitespace that caused overflow
                            token_str = "";
                            token_len = 0;
                        }
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
        let caps = get_re(&RE_ANSI_PARTS).captures(code);
        if caps.is_none() {
            return;
        }
        let content = caps.unwrap().get(1).map_or("", |m| m.as_str());

        // Reset
        if content == "0" || content.is_empty() {
            state.clear();
            return;
        }

        let first_num: i32 = content
            .split(';')
            .next()
            .unwrap_or("0")
            .parse()
            .unwrap_or(0);
        let category = match first_num {
            1 | 22 => "bold",
            3 | 23 => "italic",
            4 | 24 => "underline",
            9 | 29 => "strike",
            30..=39 | 90..=97 => "fg",
            40..=49 | 100..=107 => "bg",
            _ => "other",
        };

        if category != "other" {
            state.retain(|existing| {
                let c_caps = get_re(&RE_ANSI_PARTS).captures(existing);
                if let Some(cc) = c_caps {
                    let c_content = cc.get(1).map_or("", |m| m.as_str());
                    let c_num: i32 = c_content
                        .split(';')
                        .next()
                        .unwrap_or("0")
                        .parse()
                        .unwrap_or(0);
                    let c_cat = match c_num {
                        1 | 22 => "bold",
                        3 | 23 => "italic",
                        4 | 24 => "underline",
                        9 | 29 => "strike",
                        30..=39 | 90..=97 => "fg",
                        40..=49 | 100..=107 => "bg",
                        _ => "other",
                    };
                    c_cat != category
                } else {
                    true
                }
            });
        }
        state.push(code.to_string());
    }

    // --- Table Logic ---
    fn render_stream_table_row<W: Write>(&mut self, w: &mut W, row_str: &str) -> io::Result<()> {
        let term_width = self.get_width();

        let cells: Vec<&str> = row_str.trim().trim_matches('|').split('|').collect();
        let col_count = cells.len();
        if col_count == 0 {
            return Ok(());
        }

        let prefix_width = self.margin + (self.blockquote_depth * 2);
        let right_margin = self.margin;
        let total_overhead = prefix_width + right_margin + 1 + (col_count * 3);
        let available_text_space = term_width.saturating_sub(total_overhead);
        if available_text_space == 0 {
            return Ok(());
        }

        let base_col_width = available_text_space / col_count;
        let remainder = available_text_space % col_count;

        let mut wrapped_cells: Vec<Vec<String>> = Vec::new();
        let mut max_height = 0;

        let bg_color = if !self.table_header_printed {
            COL_TABLE_HEAD
        } else {
            COL_TABLE_BODY
        };

        for (i, cell) in cells.iter().enumerate() {
            let clean_cell = cell.trim();
            // Remainder goes to last column
            let my_width = if i == col_count - 1 {
                base_col_width + remainder
            } else {
                base_col_width
            };
            let width = std::cmp::max(1, my_width);

            // 1. Render style FIRST (preserves Markdown across wraps)
            let styled_text = if !self.table_header_printed {
                format!(
                    "\x1b[1;33m{}\x1b[0m",
                    self.render_inline_to_string(clean_cell, Some(bg_color), Some("\x1b[1;33m"))
                )
            } else {
                self.render_inline_to_string(clean_cell, Some(bg_color), None)
            };

            // 2. Wrap using ANSI-aware logic
            let lines = self.wrap_ansi(&styled_text, width);

            if lines.len() > max_height {
                max_height = lines.len();
            }
            wrapped_cells.push(lines);
        }
        if max_height == 0 {
            max_height = 1;
        }

        let mut prefix = " ".repeat(self.margin);
        if self.blockquote_depth > 0 {
            prefix.push_str("\x1b[38;5;240m");
            for _ in 0..self.blockquote_depth {
                prefix.push_str("│ ");
            }
            prefix.push_str("\x1b[0m");
        }

        for i in 0..max_height {
            queue!(w, Print(&prefix))?;

            for (col_idx, cell_lines) in wrapped_cells.iter().enumerate() {
                let my_width = if col_idx == col_count - 1 {
                    base_col_width + remainder
                } else {
                    base_col_width
                };
                let target_width = std::cmp::max(1, my_width);

                // Cell lines are already styled Strings
                let styled_text: &str = if i < cell_lines.len() {
                    &cell_lines[i]
                } else {
                    ""
                };

                let vis_len = self.visible_width(styled_text);
                let padding = target_width.saturating_sub(vis_len);

                // Print Cell: [BG] [Space] [Text] [BG] [Padding] [Reset]
                queue!(
                    w,
                    SetBackgroundColor(bg_color),
                    Print(" "),
                    Print(styled_text),
                    SetBackgroundColor(bg_color),
                    Print(" ".repeat(padding + 1)),
                    ResetColor
                )?;

                // Print Separator only BETWEEN columns
                if col_idx < col_count - 1 {
                    queue!(
                        w,
                        SetBackgroundColor(bg_color),
                        SetForegroundColor(Color::White),
                        Print("│"),
                        ResetColor
                    )?;
                }
            }
            queue!(w, Print("\n"))?;
        }

        self.table_header_printed = true;
        Ok(())
    }

    fn render_code_line<W: Write>(&mut self, w: &mut W, line: &str) -> io::Result<()> {
        let width = self.get_width();
        let line_content = line.trim_end_matches(&['\r', '\n'][..]);

        let prefix = " ".repeat(self.margin);
        let prefix_width = self.margin;
        let right_margin = self.margin;

        let available_width = width.saturating_sub(prefix_width + right_margin);

        let mut highlighted_spans = Vec::new();
        if let Some(h) = &mut self.highlighter {
            if let Ok(ranges) = h.highlight_line(line_content, SYNTAX_SET.get().unwrap()) {
                highlighted_spans = ranges;
            } else {
                highlighted_spans.push((syntect::highlighting::Style::default(), line_content));
            }
        } else {
            highlighted_spans.push((syntect::highlighting::Style::default(), line_content));
        }

        let mut current_line_len = 0;
        let mut current_line_spans: Vec<(Color, String)> = Vec::new();

        let print_wrapped_line =
            |w: &mut W, spans: &Vec<(Color, String)>, len: usize| -> io::Result<()> {
                queue!(w, Print(&prefix))?;
                queue!(w, SetBackgroundColor(COL_CODE_BG))?;

                for (col, text) in spans {
                    queue!(w, SetForegroundColor(*col), Print(text))?;
                }

                let pad_len = available_width.saturating_sub(len);
                queue!(w, Print(" ".repeat(pad_len)), ResetColor, Print("\n"))
            };

        for (style, text) in highlighted_spans {
            let fg = style.foreground;
            let color = Color::Rgb {
                r: fg.r,
                g: fg.g,
                b: fg.b,
            };

            for char in text.chars() {
                let char_width = if char == '\t' { 4 } else { 1 };

                if current_line_len + char_width > available_width {
                    print_wrapped_line(w, &current_line_spans, current_line_len)?;
                    current_line_spans.clear();
                    current_line_len = 0;
                }

                if let Some(last) = current_line_spans.last_mut() {
                    if last.0 == color {
                        last.1.push(char);
                    } else {
                        current_line_spans.push((color, char.to_string()));
                    }
                } else {
                    current_line_spans.push((color, char.to_string()));
                }
                current_line_len += char_width;
            }
        }

        print_wrapped_line(w, &current_line_spans, current_line_len)?;
        Ok(())
    }

    pub fn render_inline_to_string(
        &self,
        text: &str,
        default_bg: Option<Color>,
        restore_fg: Option<&str>,
    ) -> String {
        let re_link = get_re(&RE_LINK);
        let re_tok = get_re(&RE_TOKENIZER);

        let text_linked = re_link.replace_all(text, |caps: &regex::Captures| {
            let link_text = caps.get(1).map_or("", |m| m.as_str());
            let link_url = caps.get(2).map_or("", |m| m.as_str());
            format!(
                "\x1b]8;;{}\x1b\\\x1b[33m\x1b[4m{}\x1b[24m\x1b[39m\x1b[39m\x1b]8;;\x1b\\",
                link_url, link_text
            )
        });

        let mut out = String::new();
        let mut in_bold = false;
        let mut in_italic = false;
        let mut in_strike = false;
        let mut in_code = false;
        let mut in_underline = false;

        for caps in re_tok.captures_iter(&text_linked) {
            let token_match = match caps.get(1) {
                Some(m) => m,
                None => continue,
            };
            let token = token_match.as_str();

            if token.starts_with('`') {
                in_code = !in_code;
                if in_code {
                    out.push_str("\x1b[48;2;60;60;60m\x1b[38;2;255;255;255m");
                } else {
                    if let Some(bg) = default_bg {
                        let (r, g, b) = match bg {
                            Color::Rgb { r, g, b } => (r, g, b),
                            _ => (0, 0, 0),
                        };
                        out.push_str(&format!("\x1b[48;2;{};{};{}m", r, g, b));
                    } else {
                        out.push_str("\x1b[49m");
                    }
                    if let Some(fg) = restore_fg {
                        out.push_str(fg);
                    } else {
                        out.push_str("\x1b[39m");
                    }
                }
                let body = token.trim_matches('`');
                if !body.is_empty() {
                    out.push_str(body);
                }
            } else if in_code {
                out.push_str(token);
            } else if token.starts_with('$') && token.ends_with('$') && token.len() > 1 {
                let content = &token[1..token.len() - 1];
                out.push_str(&unicodeit::replace(content));
            } else {
                match token {
                    "***" | "___" => {
                        in_bold = !in_bold;
                        in_italic = !in_italic;
                        out.push_str(if in_bold { "\x1b[1m" } else { "\x1b[22m" });
                        out.push_str(if in_italic { "\x1b[3m" } else { "\x1b[23m" });
                    }
                    "**" | "__" => {
                        in_bold = !in_bold;
                        out.push_str(if in_bold { "\x1b[1m" } else { "\x1b[22m" });
                    }
                    "*" => {
                        in_italic = !in_italic;
                        out.push_str(if in_italic { "\x1b[3m" } else { "\x1b[23m" });
                    }
                    "_" => {
                        let prev_char = out.chars().last().unwrap_or(' ');
                        let next_char = text_linked[token_match.end()..]
                            .chars()
                            .next()
                            .unwrap_or(' ');

                        let prev_is_text = prev_char.is_alphanumeric();
                        let next_is_text = next_char.is_alphanumeric();

                        // Python Parity: Toggle if currently underlining OR if we are at start of a word
                        if in_underline || (!prev_is_text && next_is_text) {
                            in_underline = !in_underline;
                            out.push_str(if in_underline { "\x1b[4m" } else { "\x1b[24m" });
                        } else {
                            out.push('_');
                        }
                    }
                    "~~" => {
                        in_strike = !in_strike;
                        out.push_str(if in_strike { "\x1b[9m" } else { "\x1b[29m" });
                    }
                    _ => out.push_str(token),
                }
            }
        }
        out
    }

    fn start_highlighter(&mut self, lang: &str) {
        let ss = SYNTAX_SET.get().unwrap();
        let syntax = ss
            .find_syntax_by_token(lang)
            .unwrap_or_else(|| ss.find_syntax_plain_text());
        self.highlighter = Some(HighlightLines::new(syntax, THEME.get().unwrap()));
    }
}
