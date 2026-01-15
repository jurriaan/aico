use crate::historystore::store::HistoryStore;
use crate::models::Role;
use crate::models::{SessionView, TokenUsage};
use crossterm::style::Stylize;
use std::io::IsTerminal;
use unicode_width::UnicodeWidthStr;

pub const ANSI_REGEX_PATTERN: &str = r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b].*?(\x1b\\|[\x07])";

pub fn strip_ansi_codes(s: &str) -> String {
    static RE: std::sync::LazyLock<regex::Regex> =
        std::sync::LazyLock::new(|| regex::Regex::new(ANSI_REGEX_PATTERN).unwrap());
    RE.replace_all(s, "").to_string()
}

pub fn get_terminal_width() -> usize {
    static TERMINAL_WIDTH: std::sync::LazyLock<usize> = std::sync::LazyLock::new(|| {
        // 1. Check AICO_COLUMNS
        if let Ok(w) = std::env::var("AICO_COLUMNS").map(|s| s.parse().unwrap_or(0))
            && w > 0
        {
            return w;
        }

        // 2. Check COLUMNS
        if let Ok(w) = std::env::var("COLUMNS").map(|s| s.parse().unwrap_or(0))
            && w > 0
        {
            return w;
        }

        // 3. System TTY (Only called if env vars are missing)
        if is_stdout_terminal()
            && let Ok((w, _)) = crossterm::terminal::size()
        {
            return w as usize;
        }

        // 4. Default Fallback
        80
    });

    *TERMINAL_WIDTH
}

pub fn draw_panel(title: &str, lines: &[String], width: usize) {
    let inner_width = width.saturating_sub(2);
    let title_fmt = if !title.is_empty() {
        format!(" {} ", title)
    } else {
        "".to_string()
    };

    let title_width = UnicodeWidthStr::width(title_fmt.as_str());
    let total_dashes = inner_width.saturating_sub(title_width);
    let left_dashes = total_dashes / 2;
    let right_dashes = total_dashes - left_dashes;

    println!(
        "╭{}{}{}╮",
        "─".repeat(left_dashes),
        title_fmt,
        "─".repeat(right_dashes)
    );

    for line in lines {
        let stripped = strip_ansi_codes(line);
        let visible_len = UnicodeWidthStr::width(stripped.as_str());
        let total_padding = inner_width.saturating_sub(visible_len);
        let left_padding = total_padding / 2;
        let right_padding = total_padding - left_padding;

        println!(
            "│{}{}{}│",
            " ".repeat(left_padding),
            line,
            " ".repeat(right_padding)
        );
    }

    println!("╰{}╯", "─".repeat(inner_width));
}

pub fn is_stdout_terminal() -> bool {
    if std::env::var("AICO_FORCE_TTY").is_ok() {
        return true;
    }
    std::io::stdout().is_terminal()
}

pub fn is_stdin_terminal() -> bool {
    std::io::stdin().is_terminal()
}

use crate::models::Mode;

pub fn format_piped_output<'a>(
    unified_diff: &'a Option<String>,
    raw_content: &'a str,
    mode: &Mode,
) -> &'a str {
    if matches!(mode, Mode::Diff) {
        return unified_diff.as_deref().unwrap_or("");
    }

    if let Some(diff) = unified_diff
        && !diff.is_empty()
    {
        return diff.as_str();
    }

    raw_content
}

pub fn format_tokens(n: u32) -> String {
    if n >= 1000 {
        format!("{:.1}k", n as f64 / 1000.0)
    } else {
        n.to_string()
    }
}

pub fn format_thousands(n: u32) -> String {
    let s = n.to_string();
    let len = s.len();
    let num_commas = (len.saturating_sub(1)) / 3;
    let mut result = String::with_capacity(len + num_commas);

    let offset = len % 3;
    let mut chars = s.chars();

    if offset > 0 {
        for _ in 0..offset {
            result.push(chars.next().unwrap());
        }
    }

    for (i, c) in chars.enumerate() {
        if i % 3 == 0 && (offset > 0 || i > 0) {
            result.push(',');
        }
        result.push(c);
    }
    result
}

pub fn display_cost_summary(
    usage: &TokenUsage,
    current_cost: Option<f64>,
    store: &HistoryStore,
    view: &SessionView,
) {
    let mut prompt_info = format_tokens(usage.prompt_tokens);
    if let Some(cached) = usage.cached_tokens
        && cached > 0
    {
        prompt_info.push_str(&format!(" ({} cached)", format_tokens(cached)));
    }

    let mut completion_info = format_tokens(usage.completion_tokens);
    if let Some(reasoning) = usage.reasoning_tokens
        && reasoning > 0
    {
        completion_info.push_str(&format!(" ({} reasoning)", format_tokens(reasoning)));
    }

    let mut info = format!(
        "Tokens: {} sent, {} received.",
        prompt_info, completion_info
    );

    if let Some(cost) = current_cost {
        let mut history_cost = 0.0;

        if let Ok(records) = store.read_many(&view.message_indices) {
            let start_idx = view.history_start_pair * 2;
            for (i, record) in records.iter().enumerate() {
                if i >= start_idx
                    && record.role == Role::Assistant
                    && let Some(c) = record.cost
                {
                    history_cost += c;
                }
            }
        }

        let total_chat = history_cost + cost;
        info.push_str(&format!(
            " Cost: ${:.2}, current chat: ${:.2}",
            cost, total_chat
        ));
    }

    if is_stdout_terminal() {
        eprintln!("{}", "---".dim());
        eprintln!("{}", info.dim());
    } else {
        eprintln!("{}", info);
    }
}
