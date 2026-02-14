use aico::console::strip_ansi_codes;
use aico::ui::markdown_streamer::MarkdownStreamer;

// --- Constants for strict ANSI Expectation ---
// Matches logic in markdown_streamer.rs
const BOLD: &str = "\x1b[1m";
const BOLD_OFF: &str = "\x1b[22m";
const ITALIC: &str = "\x1b[3m";
const ITALIC_OFF: &str = "\x1b[23m";
const UNDERLINE: &str = "\x1b[4m"; // Streamer uses Underline for "_"
const UNDERLINE_OFF: &str = "\x1b[24m";

// Standard wrapping used by render_standard_text (Reset, SetAttr(Reset) ... Content ... Reset, Newline)
const PREFIX: &str = "\x1b[0m\x1b[0m";
const SUFFIX: &str = "\x1b[0m\n";

/// Helper to render markdown and return both raw (with ANSI) and cleaned output.
fn render(input: &str, width: usize, margin: usize) -> (String, String) {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_width(width);
    streamer.set_margin(margin);
    let mut sink = Vec::new();
    streamer.print_chunk(&mut sink, input).unwrap();
    streamer.flush(&mut sink).unwrap();
    let raw = String::from_utf8_lossy(&sink).to_string();
    let clean = strip_ansi_codes(&raw);
    (raw, clean)
}

macro_rules! inline_tests {
    ($($name:ident: {
        input: $input:expr
        $(, $k:ident: $v:tt)*
        $(,)?
    }),* $(,)?) => {
        $(
            #[test]
            #[allow(unused_mut, unused_assignments)]
            fn $name() {
                let mut width = 1000;
                let mut margin = 0;
                let mut raw: Option<Vec<&str>> = None;
                let mut raw_contains: Option<&str> = None;
                let mut not_raw: Option<&str> = None;
                let mut clean: Option<&str> = None;
                let mut contains: Option<&str> = None;

                $(
                    inline_tests!(@attr $k, $v, width, margin, raw, raw_contains, not_raw, clean, contains);
                )*

                #[allow(unused_variables)]
                let (raw_out, clean_out) = render($input, width, margin);

                if let Some(r) = raw {
                    let mut expected_raw = String::from(PREFIX);
                    for s in r { expected_raw.push_str(s); }
                    expected_raw.push_str(SUFFIX);
                    assert_eq!(raw_out, expected_raw, "RAW mismatch for {}", stringify!($name));
                }
                if let Some(rc) = raw_contains {
                    assert!(raw_out.contains(rc), "RAW_CONTAINS mismatch for {}: expected to contain {:?}", stringify!($name), rc);
                }
                if let Some(nr) = not_raw {
                    assert!(!raw_out.contains(nr), "NOT_RAW mismatch for {}: expected to NOT contain {:?}", stringify!($name), nr);
                }
                if let Some(c) = clean {
                    assert_eq!(clean_out, c, "CLEAN mismatch for {}", stringify!($name));
                }
                if let Some(con) = contains {
                    let normalized = clean_out.lines().map(|l| l.trim_end()).collect::<Vec<_>>().join("\n");
                    assert!(normalized.contains(con) || clean_out.contains(con), "CONTAINS mismatch for {}: expected to contain {:?}", stringify!($name), con);
                }
            }
        )*
    };
    (@attr width, $v:expr, $width:ident, $margin:ident, $raw:ident, $raw_contains:ident, $not_raw:ident, $clean:ident, $contains:ident) => { $width = $v; };
    (@attr margin, $v:expr, $width:ident, $margin:ident, $raw:ident, $raw_contains:ident, $not_raw:ident, $clean:ident, $contains:ident) => { $margin = $v; };
    (@attr raw, [$($r:expr),*], $width:ident, $margin:ident, $raw:ident, $raw_contains:ident, $not_raw:ident, $clean:ident, $contains:ident) => { $raw = Some(vec![$($r),*]); };
    (@attr raw_contains, $v:expr, $width:ident, $margin:ident, $raw:ident, $raw_contains:ident, $not_raw:ident, $clean:ident, $contains:ident) => { $raw_contains = Some($v); };
    (@attr not_raw, $v:expr, $width:ident, $margin:ident, $raw:ident, $raw_contains:ident, $not_raw:ident, $clean:ident, $contains:ident) => { $not_raw = Some($v); };
    (@attr clean, $v:expr, $width:ident, $margin:ident, $raw:ident, $raw_contains:ident, $not_raw:ident, $clean:ident, $contains:ident) => { $clean = Some($v); };
    (@attr contains, $v:expr, $width:ident, $margin:ident, $raw:ident, $raw_contains:ident, $not_raw:ident, $clean:ident, $contains:ident) => { $contains = Some($v); };
}

inline_tests! {
    rule_01_a: { input: "*foo bar*", raw: [ITALIC, "foo bar", ITALIC_OFF] },
    rule_01_b: { input: "a * foo bar*", clean: "a * foo bar*\n" },
    rule_01_c: { input: "a*\"foo\"*", clean: "a*\"foo\"*\n" },
    rule_01_d: { input: "x * a *", clean: "x * a *\n" },
    rule_01_e: { input: "foo*bar*", raw: ["foo", ITALIC, "bar", ITALIC_OFF] },
    rule_01_f: { input: "5*6*78", raw: ["5", ITALIC, "6", ITALIC_OFF, "78"] },

    rule_02_a: { input: "_foo bar_", raw: [UNDERLINE, "foo bar", UNDERLINE_OFF] },
    rule_02_b: { input: "_ foo bar_", clean: "_ foo bar_\n" },
    rule_02_c: { input: "a_\"foo\"_", clean: "a_\"foo\"_\n" },
    rule_02_d: { input: "foo_bar_", clean: "foo_bar_\n" },
    rule_02_e: { input: "5_6_78", clean: "5_6_78\n" },
    rule_02_f: { input: "foo-_(bar)_", raw: ["foo-", UNDERLINE, "(bar)", UNDERLINE_OFF] },

    rule_03_a: { input: "_foo*", clean: "_foo*\n" },
    rule_03_b: { input: "*foo bar *", clean: "*foo bar *\n" },
    rule_03_c: { input: "*(*foo)", clean: "*(*foo)\n" },
    rule_03_d: { input: "*foo*bar", raw: [ITALIC, "foo", ITALIC_OFF, "bar"] },

    rule_04_a: { input: "_foo bar _", clean: "_foo bar _\n" },
    rule_04_b: { input: "_(_foo)", clean: "_(_foo)\n" },
    rule_04_c: { input: "_(_foo_)_", raw: [UNDERLINE, "(", UNDERLINE, "foo", UNDERLINE_OFF, ")", UNDERLINE_OFF] },
    rule_04_d: { input: "_foo_bar", clean: "_foo_bar\n" },
    rule_04_e: { input: "_foo_bar_baz_", raw: [UNDERLINE, "foo_bar_baz", UNDERLINE_OFF] },
    rule_04_f: { input: "_(bar)_.", raw: [UNDERLINE, "(bar)", UNDERLINE_OFF, "."] },

    rule_05_a: { input: "**foo bar**", raw: [BOLD, "foo bar", BOLD_OFF] },
    rule_05_b: { input: "** foo bar**", clean: "** foo bar**\n" },
    rule_05_c: { input: "a**\"foo\"**", clean: "a**\"foo\"**\n" },
    rule_05_d: { input: "foo**bar**", raw: ["foo", BOLD, "bar", BOLD_OFF] },

    rule_06_a: { input: "__foo bar__", raw: [BOLD, "foo bar", BOLD_OFF] },
    rule_06_b: { input: "__ foo bar__", clean: "__ foo bar__\n" },
    rule_06_c: { input: "foo__bar__", clean: "foo__bar__\n" },
    rule_06_d: { input: "5__6__78", clean: "5__6__78\n" },
    rule_06_e: { input: "foo-__(bar)__", raw: ["foo-", BOLD, "(bar)", BOLD_OFF] },

    rule_09_a: { input: "_foo __bar__ baz_", raw: [UNDERLINE, "foo ", BOLD, "bar", BOLD_OFF, " baz", UNDERLINE_OFF] },
    rule_09_b: { input: "*foo **bar** baz*", raw: [ITALIC, "foo ", BOLD, "bar", BOLD_OFF, " baz", ITALIC_OFF] },
    rule_09_c: { input: "***foo** bar*", raw: [ITALIC, BOLD, "foo", BOLD_OFF, " bar", ITALIC_OFF] },
    rule_09_d: { input: "*foo **bar***", raw: [ITALIC, "foo ", BOLD, "bar", BOLD_OFF, ITALIC_OFF] },

    rule_11_a: { input: "foo \\*bar\\*", clean: "foo *bar*\n" },
    rule_11_b: { input: "foo * bar", clean: "foo * bar\n" },
    rule_11_c: { input: "***foo**", raw: ["*", BOLD, "foo", BOLD_OFF] },

    rule_12_a: { input: "foo \\_bar\\_", clean: "foo _bar_\n" },

    rule_14_a: { input: "***foo***", raw: [ITALIC, BOLD, "foo", BOLD_OFF, ITALIC_OFF] },

    rule_16_a: { input: "**foo **bar baz**", raw: ["**foo ", BOLD, "bar baz", BOLD_OFF] },

    empty_emphasis: { input: "** is not an empty emphasis", clean: "** is not an empty emphasis\n" },
    empty_emphasis_strong: { input: "**** is not an empty strong emphasis", clean: "**** is not an empty strong emphasis\n" },

    commonmark_codespan_01: { input: "`foo`", clean: "foo\n" },
    commonmark_codespan_02: { input: "`` foo ` bar ``", clean: "foo ` bar\n" },
    commonmark_codespan_03: { input: "``foo`bar``", clean: "foo`bar\n" },
    commonmark_codespan_04: { input: "*foo`*`", clean: "*foo*\n" },
    commonmark_codespan_05: { input: "` `` `", clean: "``\n" },
    commonmark_codespan_06: { input: "`  ``  `", clean: " `` \n" },
    commonmark_codespan_07: { input: "` a`", clean: " a\n" },
    commonmark_codespan_08: { input: "` b `", clean: " b \n" },
    commonmark_codespan_09: { input: "` `", clean: " \n" },
    commonmark_codespan_10: { input: "`  `", clean: "  \n" },
    commonmark_codespan_11: { input: "``\nfoo\nbar\n``", clean: "foo bar\n" },
    commonmark_codespan_12: { input: "`foo   bar \nbaz`", clean: "foo   bar  baz\n" },

    fence_tilde_support: { input: "~~~bash\n```\necho hello\n```\n~~~\n", contains: "```", raw_contains: "\x1b[0m" },
    fence_backtick_info_constraint: { input: "```info`string\ncontent\n", not_raw: "48;2;30;30;30m" },
    fence_inline_tilde_preservation: { input: "Use `` `~~~` `` to show tildes.\n", contains: "`~~~`" },
    fence_block_containing_tildes: { input: "```markdown\nThis block contains ~~~ as text.\n```\n", contains: "~~~" },
    fence_inline_bg_1: { input: "Text `code` Text\n", raw_contains: "48;2;60;60;60m" },
    fence_inline_bg_2: { input: "Text `` double code `` Text\n", raw_contains: "48;2;60;60;60m" },

    fence_indent_stripping: { input: "  ```\n  def foo():\n    return True\n  ```\n", contains: "def foo():\n  return True", not_raw: "  def foo()" },
    tab_expansion_list: { input: "-\tList Item\n", clean: "•   List Item\n" },
    autolink_basic: { input: "Visit <https://example.com> now.\n", clean: "Visit https://example.com now.\n", raw_contains: "\x1b]8;;https://example.com\x1b\\" },
    atx_closing_hashes: { input: "## Title ##", contains: "Title", raw_contains: BOLD },
    escaped_ordered_list_marker: { input: "1986\\. What a year.\n", clean: "1986. What a year.\n", not_raw: "\x1b[33m" },
    code_block_background_color: { input: "```\ncode\n```\n", raw_contains: "48;2;30;30;30m" },

    // §4.1 Thematic break edge cases
    thematic_break_indent_1: { input: " ---\n", contains: "─" },
    thematic_break_indent_2: { input: "  ---\n", contains: "─" },
    thematic_break_indent_3: { input: "   ---\n", contains: "─" },
    thematic_break_many_chars: { input: "_____________________________________\n", contains: "─" },
    thematic_break_trailing_spaces: { input: "- - - -    \n", contains: "─" },

    // §4.2 ATX Heading edge cases
    heading_7_hashes_not_heading: { input: "####### foo\n", clean: "####### foo\n" },
    heading_no_space_not_heading: { input: "#5 bolt\n", clean: "#5 bolt\n" },
    heading_hashtag_not_heading: { input: "#hashtag\n", clean: "#hashtag\n" },

    // §6.7 Hard line breaks
    hard_break_two_trailing_spaces: { input: "foo  \nbar\n", contains: "foo" },
    hard_break_two_trailing_spaces_bar: { input: "foo  \nbar\n", contains: "bar" },
    hard_break_trailing_backslash: { input: "foo\\\nbar\n", contains: "foo" },
    hard_break_trailing_backslash_bar: { input: "foo\\\nbar\n", contains: "bar" },

    // §5.2 List item with `+` marker
    list_plus_marker: { input: "+ Item\n", contains: "• Item" },

    // §5.2 Ordered list start > 1
    list_ordered_start_3: { input: "3. Third\n", contains: "3. Third" },
}

#[test]
fn fence_length_mismatch() {
    let input = "````\n```\ncontent\n```\n````\n";
    let (_, clean) = render(input, 1000, 0);

    let normalized: String = clean
        .lines()
        .map(|line| line.trim_end())
        .collect::<Vec<_>>()
        .join("\n");

    assert!(
        normalized.contains("```\ncontent\n```"),
        "Nested code fences were not correctly parsed as literal content.\nOutput:\n{}",
        normalized
    );
}

#[test]
fn test_dedent_behavior_correctness() {
    let input = "  - Indented Item\n1. Root Item\n";
    let (_, clean) = render(input, 1000, 2);
    let expected = "  • Indented Item\n  1. Root Item\n";
    assert_eq!(clean, expected, "Rendered output did not match expectation");
}

#[test]
fn test_list_numbering_preserved_after_code_block() {
    let input = "1. Item One\n```\ncode\n```\n2. Item Two\n";
    let (_, clean) = render(input, 1000, 2);

    let normalized = clean.replace("\r\n", "\n");
    assert!(
        normalized.contains("  1. Item One"),
        "Item 1 missing or wrong indent"
    );
    assert!(
        normalized.contains("    code"),
        "Code block missing correct indentation (should be 4 spaces)"
    );
    assert!(
        normalized.contains("  2. Item Two"),
        "Item 2 missing or wrong indent"
    );
}

#[test]
fn test_list_integrity_and_empty_item_spacing() {
    let input = "1. \n   ```text\n   indented content\n   ```\n2. Item Two\n";
    let (_, cleaned) = render(input, 1000, 0);
    let lines: Vec<&str> = cleaned.lines().collect();

    assert_eq!(lines[0].trim(), "1.", "List item 1 should be isolated.");

    let code_line = lines
        .iter()
        .find(|l| l.contains("indented content"))
        .expect("Code content missing");
    assert!(
        code_line.starts_with("   indented"),
        "Code content indent failed. Expected 3 spaces (matching '1. '). Got: '{}'",
        code_line
    );

    let item_two = lines
        .iter()
        .find(|l| l.contains("Item Two"))
        .expect("Item Two missing");
    assert!(
        item_two.starts_with("2. "),
        "Item Two should be at root. Got: '{}'",
        item_two
    );
}

#[test]
fn test_list_numbering_preserved_after_table() {
    let input = "1. Item One\n| A | B |\n|---|---|\n| 1 | 2 |\n2. Item Two\n";
    let (_, clean) = render(input, 20, 2);

    let normalized: String = clean
        .lines()
        .map(|line| line.trim_end())
        .collect::<Vec<_>>()
        .join("\n");

    let expected = "  1. Item One\n   A     │ B\n   1     │ 2\n  2. Item Two";
    assert_eq!(
        normalized, expected,
        "List numbering should be preserved after a table"
    );
}

#[test]
fn test_hyperlink_osc8_wrapping_and_width() {
    // Verifies invisible URL width calculation and prevents OSC 8 sequence fragmentation.
    let input = "Start \x1b]8;;https://very-long-url-that-exceeds-width.com/path\x1b\\Link\x1b]8;;\x1b\\ End\n";
    let (raw, _) = render(input, 20, 2);

    assert!(
        !raw.contains("];;"),
        "Output contained broken OSC 8 artifacts, indicating the escape sequence was split."
    );
    assert_eq!(
        raw.lines().count(),
        1,
        "Text wrapped unexpectedly. The invisible URL characters were likely counted towards line width."
    );
}

#[test]
fn test_table_background_preserved_after_inline_code() {
    // Ensures table cell background color is restored after an inline code block.
    let input = "| Header |\n|---|\n| Pre `code` Post |\n";
    let (raw, _) = render(input, 100, 2);

    let table_bg_seq = "\x1b[48;2;30;30;30m";
    let reset_bg_seq = "\x1b[49m";
    let post_idx = raw
        .find("Post")
        .expect("Could not find cell content 'Post'");
    let window = &raw[post_idx.saturating_sub(50)..post_idx];

    assert!(
        window.contains(table_bg_seq),
        "After inline code in a table, the background was not restored to table color."
    );
    assert!(
        !window.contains(reset_bg_seq),
        "After inline code in a table, the background was incorrectly reset to default."
    );
}

#[test]
fn test_math_collision_inside_code_blocks() {
    // Prevents math parser from mangling shell variables like ${VAR} inside code spans.
    let input = "Run `echo \"${CYAN}Hello${NC}\"` to start.\n";
    let (raw, clean) = render(input, 1000, 2);

    assert!(
        raw.contains("${CYAN}"),
        "The string ${{CYAN}} was modified or removed. Math parser likely consumed it."
    );
    assert!(
        clean.contains("echo \"${CYAN}Hello${NC}\""),
        "The content inside backticks was altered."
    );
}

#[test]
fn test_header_style_preserved_after_inline_code() {
    // Ensures header colors/styles are restored after inline code blocks.
    let input = "### Header `code` Policy\n";
    let (raw, _) = render(input, 1000, 2);

    let policy_idx = raw
        .find(" Policy")
        .expect("Could not find cell content ' Policy'");
    let window = &raw[policy_idx.saturating_sub(40)..policy_idx];

    assert!(
        !window.contains("\x1b[39m"),
        "After inline code in a header, the foreground was incorrectly reset to default terminal color."
    );
    assert!(
        window.contains("36"),
        "Header color (Cyan/36) was not restored after inline code."
    );
}

#[test]
fn test_emphasis_flanking_rules_comprehensive() {
    let input = "1. a * not italic * b\n2. perform_action_now\n3. a*b*\n";
    let (raw, cleaned) = render(input, 1000, 2);

    assert!(
        cleaned.contains("a * not italic * b"),
        "Whitespace Flanking Failed: Asterisks were consumed."
    );
    if let Some(line1_end) = raw.find('\n') {
        assert!(
            !raw[..line1_end].contains("\x1b[3m"),
            "Whitespace Flanking Failed: ANSI italic found."
        );
    }

    assert!(
        cleaned.contains("perform_action_now"),
        "Snake_case Rule Failed: Underscores were consumed."
    );
    if let Some(start) = raw.find("2. perform") {
        if let Some(end) = raw[start..].find('\n') {
            let l2 = &raw[start..start + end];
            assert!(
                !l2.contains("\x1b[4m") && !l2.contains("\x1b[3m"),
                "Snake_case Rule Failed: ANSI styling found."
            );
        }
    }

    assert!(
        !cleaned.contains("a*b*"),
        "Intraword Asterisk Rule Failed: Asterisks remained literal."
    );
    assert!(
        raw.contains("a\x1b[3mb\x1b"),
        "Intraword Asterisk Rule Failed: No italic sequence found."
    );
}

#[test]
fn test_list_alignment_and_nesting_comprehensive() {
    let input = "- Bullet Item\n  Indented Continuation\n- Lazy Parent\nLazy Continuation\n";
    let (_, clean) = render(input, 1000, 0);
    let lines: Vec<&str> = clean.lines().collect();

    assert!(
        lines[1].starts_with("  Indented"),
        "Explicit Indent Failed."
    );
    assert!(
        !lines[3].starts_with(" "),
        "Lazy Continuation / List Exit Failed."
    );
}

#[test]
fn test_list_integrity_with_interleaved_code_blocks() {
    let input = "1. Step One\n   ```bash\n   echo 'inside code'\n   ```\n2. Step Two\n";
    let (raw, clean) = render(input, 80, 0);
    let lines: Vec<&str> = clean.lines().collect();

    assert!(
        lines
            .iter()
            .find(|l| l.contains("inside code"))
            .unwrap()
            .starts_with("  "),
        "Code block lost indentation."
    );
    assert!(
        lines
            .iter()
            .find(|l| l.contains("Step Two"))
            .unwrap()
            .starts_with("2. "),
        "Second list item lost alignment."
    );
    assert!(
        raw.contains("\x1b[33m2."),
        "Second list item lost specific styling (Yellow)."
    );
}

#[test]
fn test_list_with_same_line_code_fence() {
    let input = "1. ```ruby\n   1+1\n   ```\n2. Next\n";
    let (_, clean) = render(input, 1000, 0);
    let lines: Vec<&str> = clean.lines().collect();

    assert_eq!(lines[0].trim(), "1.");
    assert!(lines.iter().find(|l| l.contains("1+1")).is_some());
    assert!(
        lines
            .iter()
            .find(|l| l.contains("Next"))
            .unwrap()
            .starts_with("2. ")
    );
    assert!(!clean.ends_with("```ruby"));
}

#[test]
fn test_repro_bug_01_sticky_list_indentation() {
    // Verifies that following root-level paragraphs correctly exit the list context.
    let input = "- Item 1\n- Item 2\n\nParagraph should be root.\n";
    let (_, clean) = render(input, 1000, 0);
    let paragraphs = clean.lines().last().expect("Output was empty");
    assert!(
        !paragraphs.starts_with(" "),
        "Sticky List Bug: Root paragraph retained indentation."
    );
}

#[test]
fn test_repro_bug_02_blockquote_links_and_leaking() {
    // Checks for blockquote border leaks and link tokenization corruption.
    let input = "> [Link](https://example.com)\n\nPost-quote paragraph.\n";
    let (raw, clean) = render(input, 1000, 0);
    let lines: Vec<&str> = clean.lines().collect();

    let last_line = lines.last().expect("Missing last line");
    assert!(!last_line.contains("│"), "Blockquote border leaked.");
    assert!(!last_line.starts_with(" "), "Blockquote indent leaked.");

    let link_line_raw = raw.lines().find(|l| l.contains("Link")).unwrap();
    let is_broken = |r: &str, t: &str| r.contains(t) && !r.contains(&format!("\x1b{}", t));
    assert!(
        !is_broken(link_line_raw, "[33;4m"),
        "Link Tokenization Bug Detected."
    );
    assert!(
        link_line_raw.contains("\x1b]8;;"),
        "OSC 8 sequence missing."
    );
}

#[test]
fn test_repro_bug_03_nested_list_indentation() {
    // Verifies nested list alignment relative to parent indentation (not strict 2-space).
    let input = "1. Level 1\n   1. Level 2\n      1. Level 3\n";
    let (_, clean) = render(input, 1000, 0);
    let lines: Vec<&str> = clean.lines().collect();

    let get_indent = |s: &str| s.chars().take_while(|c| *c == ' ').count();
    let i1 = get_indent(lines[0]);
    let i2 = get_indent(lines[1]);
    let i3 = get_indent(lines[2]);

    assert!(i2 > i1 && i3 > i2, "Indentation layering failed.");
    assert!(
        (i2 - i1) >= 2 && (i2 - i1) <= 4,
        "Level 2 indent delta suspicious."
    );
    assert!(
        (i3 - i2) >= 2 && (i3 - i2) <= 4,
        "Level 3 indent delta suspicious."
    );
}

#[test]
fn test_repro_bug_04_code_block_wrapping_background() {
    // Verifies manual wrapping of code blocks preserves background colors on all lines.
    let input = "```text\nAAAAABBBBBCCCCCDDDDD\n```\n";
    let (raw, _) = render(input, 20, 2);
    let content_lines: Vec<&str> = raw
        .lines()
        .filter(|l| l.contains('A') || l.contains('B') || l.contains('C') || l.contains('D'))
        .collect();

    assert!(content_lines.len() >= 2, "Code block did not wrap.");
    for line in content_lines {
        assert!(
            line.contains("48;2;30;30;30m"),
            "Wrapped line lost background color."
        );
    }
}

#[test]
fn test_repro_bug_05_ordered_list_alignment() {
    // Ensures continuation lines align with the text of the list marker (width-aware).
    let input = "1. Start\n   Continuation\n   * Nested\n";
    let (_, clean) = render(input, 1000, 0);
    let lines: Vec<&str> = clean.lines().collect();

    assert_eq!(
        lines[1].chars().take_while(|c| *c == ' ').count(),
        3,
        "Continuation misaligned."
    );
    assert_eq!(
        lines[2].chars().take_while(|c| *c == ' ').count(),
        3,
        "Nested item misaligned."
    );
}

#[test]
fn test_repro_bug_06_spec_alignment_compliance() {
    // Verifies variable marker spacing (e.g., '1.  Header') is preserved per Spec.
    let input = "1.  Header\n    Continuation\n";
    let (_, clean) = render(input, 1000, 0);
    let lines: Vec<&str> = clean.lines().collect();

    assert!(
        lines[0].contains("1.  Header"),
        "Spec Violation: Header spacing altered."
    );
    assert_eq!(
        lines[1].chars().take_while(|c| *c == ' ').count(),
        4,
        "Continuation alignment mismatch."
    );
}

#[test]
fn test_sticky_list_exit_behavior() {
    let input = "- Item 1\n  - Nested\nRoot Paragraph\n";
    let (_, clean) = render(input, 1000, 0);
    assert!(
        !clean.lines().last().unwrap().starts_with(" "),
        "Paragraph failed to exit list."
    );
}

#[test]
fn test_spec_ex_43_hr_precedence() {
    let input = "- Foo\n- * * *\n";
    let (_, clean) = render(input, 1000, 0);
    assert!(
        clean.contains("─"),
        "Thematic break should take precedence."
    );
    assert_eq!(
        clean.matches("•").count(),
        1,
        "Incorrectly rendered as nested list."
    );
}

#[test]
fn test_spec_ex_330_block_precedence() {
    let input = "- `one\n- two`\n";
    let (_, clean) = render(input, 1000, 0);
    assert_eq!(
        clean.matches("•").count(),
        2,
        "Inline code span suppressed block structure."
    );
    assert!(
        clean.contains("`one") && clean.contains("two`"),
        "List content missing."
    );
}

#[test]
fn test_tokenizer_priority_code_vs_math() {
    let input = "Code: `echo \"$VAR\" and \"$VAR\"` end.\n";
    let (raw, _) = render(input, 1000, 0);
    assert!(raw.contains("$VAR"), "Variable consumed by math parser.");
    assert!(
        !raw.contains("\x1b[3m"),
        "Math styling found inside code span."
    );
}

#[test]
fn test_spec_compliance_block_precedence_list_vs_emphasis() {
    let (_, clean1) = render("* a *\n", 1000, 0);
    let (_, clean2) = render("* **Title:**\n", 1000, 0);

    assert!(
        clean1.contains("• a *"),
        "Canonical Precedence Bug: '* a *' was not a list."
    );
    assert!(
        clean2.contains("• Title:"),
        "User Bug: '* **Title:**' was not a list."
    );
}

#[test]
fn test_spec_ex_43_thematic_break_precedence() {
    let (_, clean) = render("* Foo\n* * *\n* Bar\n", 1000, 0);
    assert_eq!(clean.matches("•").count(), 2, "Wrong number of list items.");
    assert!(clean.contains("─"), "Should contain horizontal rule.");
}

#[test]
fn test_link_nested_brackets_in_text() {
    let (raw, clean) = render("[link [foo [bar]]](/uri)\n", 1000, 0);
    assert!(raw.contains("\x1b]8;;/uri\x1b\\"), "Link to /uri missing.");
    assert!(
        clean.contains("link [foo [bar]]"),
        "Brackets corrupted in link text."
    );
}

#[test]
fn test_link_balanced_parentheses_in_url() {
    let (raw, _) = render("[link](foo(and(bar)))\n", 1000, 0);
    assert!(
        raw.contains("\x1b]8;;foo(and(bar))\x1b\\"),
        "Balanced parens in URL lost."
    );
}

#[test]
fn test_table_no_right_gap() {
    let (_, clean) = render("| A | B |\n|---|---|\n| 1 | 2 |\n", 20, 0);
    for line in clean.lines() {
        assert_eq!(line.chars().count(), 20, "Line width incorrect.");
    }
}

#[test]
fn test_table_long_cell_uses_full_width() {
    let (_, clean) = render("| AAAAAAAAAAAAAAAAAAAAAAAAAAA |\n", 30, 0);
    assert_eq!(clean.lines().count(), 1, "Table row wrapped unexpectedly.");
}

#[test]
fn test_table_streaming_partial_row_wrapping() {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    streamer.set_width(20);
    let mut sink = Vec::new();

    streamer.print_chunk(&mut sink, "| 12345678").unwrap();
    streamer.print_chunk(&mut sink, "901234567 |").unwrap();
    streamer.print_chunk(&mut sink, "\n").unwrap();
    streamer.flush(&mut sink).unwrap();

    let clean = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    assert_eq!(
        clean.lines().count(),
        1,
        "Streaming a long row caused incorrect wrapping."
    );
}

#[test]
fn test_code_block_full_width_background_sequence() {
    // Width 20, Margin 0. Line "123" (3 chars) leaves 17 chars of padding.
    let input = "```\n123\n```\n";
    let (raw, _) = render(input, 20, 0);

    let bg_seq = "48;2;30;30;30m";
    let reset_seq = "\x1b[0m";

    // Find the background color start
    let bg_start = raw.find(bg_seq).expect("Missing code background sequence");

    // Find where the background is reset
    let reset_pos = raw[bg_start..]
        .find(reset_seq)
        .expect("Missing reset sequence after background")
        + bg_start;

    // Extract the block that is supposed to have the background
    let background_block = &raw[bg_start..reset_pos];

    // VERIFY: The background block must contain the code AND the padding spaces.
    // In a 20-wide terminal, "123" with 17 spaces padding should be present
    // before the reset occurs.
    assert!(
        background_block.contains("123                 "),
        "Background color reset before padding was complete. Block was: {:?}",
        background_block
    );
}

// --- §4.1 Thematic Break Rejected Cases ---

#[test]
fn test_thematic_break_mixed_chars_rejected() {
    // Mixed characters `*-*` is NOT a thematic break
    let (_, clean) = render("*-*\n", 1000, 0);
    assert!(
        !clean.contains("─"),
        "Mixed-char thematic break should not render as HR. Output:\n{}",
        clean
    );
}

#[test]
fn test_thematic_break_extra_text_rejected() {
    // Characters with extra text: `_ _ _ _ a` is NOT a thematic break
    let (_, clean) = render("_ _ _ _ a\n", 1000, 0);
    assert!(
        !clean.contains("─"),
        "Thematic break with trailing text should not render as HR. Output:\n{}",
        clean
    );
}

// --- §4.2 ATX Heading Edge Cases ---

#[test]
fn test_heading_empty_h1() {
    let (_, clean) = render("# \n", 1000, 0);
    // Should render as a heading (with rule line for h1) but no text content
    assert!(
        clean.contains("─"),
        "Empty H1 should still render the heading rule. Output:\n{}",
        clean
    );
}

#[test]
fn test_heading_closing_hash_no_space() {
    // `# foo#` → heading text is `foo#` (closing # must be preceded by space)
    let (_, clean) = render("# foo#\n", 1000, 0);
    assert!(
        clean.contains("foo#"),
        "Closing hash without preceding space should be part of heading text. Output:\n{}",
        clean
    );
}

#[test]
fn test_heading_closing_hashes_empty() {
    // `### ###` → empty heading (all hashes are closing)
    let (raw, _) = render("### ###\n", 1000, 0);
    // Should have heading styling but no visible text content
    assert!(
        raw.contains("\x1b[1m"),
        "Empty heading should still have heading styling. Output:\n{}",
        raw
    );
}

// --- §6.7 Hard Line Breaks ---

#[test]
fn test_hard_break_two_trailing_spaces_renders_newline() {
    // Two trailing spaces at end of line should produce a hard line break
    let (_, clean) = render("foo  \nbar\n", 1000, 0);
    let lines: Vec<&str> = clean.lines().collect();
    assert!(
        lines.len() >= 2,
        "Hard line break (two spaces) should produce separate lines. Output:\n{}",
        clean
    );
    assert!(
        lines.iter().any(|l| l.contains("foo")),
        "Should contain 'foo'. Output:\n{}",
        clean
    );
    assert!(
        lines.iter().any(|l| l.contains("bar")),
        "Should contain 'bar'. Output:\n{}",
        clean
    );
}

#[test]
fn test_hard_break_trailing_backslash_renders_newline() {
    // Trailing backslash at end of line should produce a hard line break
    let (_, clean) = render("foo\\\nbar\n", 1000, 0);
    let lines: Vec<&str> = clean.lines().collect();
    assert!(
        lines.len() >= 2,
        "Hard line break (backslash) should produce separate lines. Output:\n{}",
        clean
    );
    assert!(
        lines.iter().any(|l| l.contains("foo")),
        "Should contain 'foo'. Output:\n{}",
        clean
    );
    assert!(
        lines.iter().any(|l| l.contains("bar")),
        "Should contain 'bar'. Output:\n{}",
        clean
    );
}

#[test]
fn test_hard_break_not_in_code_span() {
    // Hard breaks don't work inside code spans
    let (_, clean) = render("`code  \nspan`\n", 1000, 0);
    // Inside code span, the two trailing spaces + newline should become a space, not a break
    assert!(
        clean.contains("code"),
        "Code span content missing. Output:\n{}",
        clean
    );
    assert!(
        clean.contains("span"),
        "Code span content missing. Output:\n{}",
        clean
    );
}

// --- §5.2 List Items ---

#[test]
fn test_list_plus_marker_renders_bullet() {
    let (_, clean) = render("+ Item One\n+ Item Two\n", 1000, 0);
    assert_eq!(
        clean.matches("•").count(),
        2,
        "Plus markers should render as bullets. Output:\n{}",
        clean
    );
}

#[test]
fn test_list_changing_marker_type() {
    // Different bullet characters should all render as bullets
    let (_, clean) = render("- Dash\n* Star\n+ Plus\n", 1000, 0);
    assert_eq!(
        clean.matches("•").count(),
        3,
        "All unordered markers (-, *, +) should render as bullets. Output:\n{}",
        clean
    );
}

#[test]
fn test_list_ordered_start_gt_1() {
    let (_, clean) = render("3. Third\n4. Fourth\n", 1000, 0);
    assert!(
        clean.contains("3.") && clean.contains("Third"),
        "Ordered list starting > 1 should preserve number. Output:\n{}",
        clean
    );
    assert!(
        clean.contains("4.") && clean.contains("Fourth"),
        "Second item should also preserve number. Output:\n{}",
        clean
    );
}

#[test]
fn test_list_empty_item() {
    // `* ` with nothing after should render a bullet with no content
    let (_, clean) = render("* \n* Item\n", 1000, 0);
    assert_eq!(
        clean.matches("•").count(),
        2,
        "Empty list item should still render a bullet. Output:\n{}",
        clean
    );
}

// --- §5.1 Blockquote Edge Cases ---

#[test]
fn test_blockquote_empty() {
    // `>` alone should be a valid blockquote
    let (raw, _) = render("> \n", 1000, 0);
    assert!(
        raw.contains("│"),
        "Empty blockquote should render border. Output:\n{}",
        raw
    );
}

#[test]
fn test_table_pipe_in_inline_code() {
    // Pipe characters inside inline code spans should NOT be treated as column separators.
    let input = "| A | `B | C` |\n|---|---|\n| 1 | `2 | 3` |\n";
    let (_, clean) = render(input, 40, 0);

    // The pipe inside the code span should be preserved as literal content.
    // This assertion will fail if the pipe is incorrectly treated as a column separator.
    assert!(
        clean.contains("B | C"),
        "Pipe in inline code was incorrectly split into columns. Output:\n{}",
        clean
    );
    assert!(
        clean.contains("2 | 3"),
        "Pipe in inline code was incorrectly split into columns. Output:\n{}",
        clean
    );
}
