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
// const STRIKE: &str = "\x1b[9m";
// const STRIKE_OFF: &str = "\x1b[29m";

// Standard wrapping used by render_standard_text (Reset, SetAttr(Reset) ... Content ... Reset, Newline)
// Based on: queue!(w, ResetColor, SetAttribute(Attribute::Reset), Print(&eff_prefix), Print(&line), ResetColor, Print("\n"))
const PREFIX: &str = "\x1b[0m\x1b[0m";
const SUFFIX: &str = "\x1b[0m\n";

fn check(input: &str, expected_inner: &str) {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0); // Disable margin to simplify prefix checks
    streamer.set_width(1000); // Prevent wrapping
    let mut sink = Vec::new();

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let actual = String::from_utf8_lossy(&sink);
    let expected = format!("{}{}{}", PREFIX, expected_inner, SUFFIX);

    assert_eq!(
        actual, expected,
        "\n\nFailed Spec Compliance Test:\nInput:    {:?}\nExpected: {:?}\nActual:   {:?}\n",
        input, expected, actual
    );
}

#[test]
fn test_dedent_behavior_correctness() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    let input = "  - Indented Item\n1. Root Item\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let clean_output = strip_ansi_codes(&raw_output);

    let expected = "  • Indented Item\n  1. Root Item\n";

    assert_eq!(
        clean_output, expected,
        "Rendered output did not match expectation"
    );
}

#[test]
fn test_list_numbering_preserved_after_code_block() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();
    // Use standard margin 2

    let input = "1. Item One\n```\ncode\n```\n2. Item Two\n";
    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));

    // Expected:
    // "  1. Item One" (Margin 2)
    // "    code"      (Margin 2 + List indent 2 = 4)
    // ""
    // "  2. Item Two" (Margin 2)

    // We normalize spaces to avoid fighting over trailing newlines
    let normalized = output.replace("\r\n", "\n");

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
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0); // Strict margin checking
    let mut sink = Vec::new();

    // Input:
    // 1. (Empty text)
    //    ```text
    //    indented content
    //    ```
    // 2. Item Two
    let input = concat!(
        "1. \n",
        "   ```text\n",
        "   indented content\n",
        "   ```\n",
        "2. Item Two\n"
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let cleaned = aico::console::strip_ansi_codes(&raw_output);
    let lines: Vec<&str> = cleaned.lines().collect();

    // Verification 1: "1." is on its own line
    assert_eq!(lines[0].trim(), "1.", "List item 1 should be isolated.");

    // Verification 2: Code content is indented (stack preserved)
    // Expect 2 spaces (Margin 0 + List Depth 1 * 2 spaces)
    let code_line = lines
        .iter()
        .find(|l| l.contains("indented content"))
        .expect("Code content missing");
    assert!(
        code_line.starts_with("  indented"),
        "Code content indent failed. Got: '{}'",
        code_line
    );

    // Verification 3: Item Two is at root
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
    let mut streamer = MarkdownStreamer::new();
    // Force a narrow width to make the table rendering predictable and compact
    streamer.set_width(20);
    let mut sink = Vec::new();

    let input = "1. Item One\n| A | B |\n|---|---|\n| 1 | 2 |\n2. Item Two\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = strip_ansi_codes(&String::from_utf8_lossy(&sink));

    let normalized_output: String = raw_output
        .lines()
        .map(|line| line.trim_end())
        .collect::<Vec<_>>()
        .join("\n");

    let expected = "  \
  1. Item One
   A    │ B
   1    │ 2
  2. Item Two";

    assert_eq!(
        normalized_output, expected,
        "List numbering should be preserved after a table"
    );
}

#[test]
fn test_hyperlink_osc8_wrapping_and_width() {
    // BUG REPRODUCTION: Links
    // 1. The visible width calculation incorrectly includes the invisible URL in OSC 8 sequences.
    // 2. The wrapping logic splits the escape sequence in the middle, corrupting the terminal.
    let mut streamer = MarkdownStreamer::new();
    // Set a narrow width to force wrapping behavior on the long link
    streamer.set_width(20);
    let mut sink = Vec::new();

    // An OSC 8 link: \x1b]8;;<URL>\x1b\<TEXT>\x1b]8;;\x1b\
    // The URL is long, but the visible text "Link" is short.
    let input = "Start \x1b]8;;https://very-long-url-that-exceeds-width.com/path\x1b\\Link\x1b]8;;\x1b\\ End\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);

    // FAILURE CONDITION 1: Broken Escape Sequences
    // If the regex splits the string inside the escape sequence, we see artifacts like ";;" or "8;;"
    assert!(
        !raw_output.contains("];;"),
        "Output contained broken OSC 8 artifacts, indicating the escape sequence was split."
    );

    // FAILURE CONDITION 2: Incorrect Wrapping
    // Since "Start Link End" (approx 14 chars) fits in 20 chars, it should be on one line.
    // If the invisible URL is counted, it wraps unnecessarily.
    let lines: Vec<&str> = raw_output.lines().collect();
    assert_eq!(
        lines.len(),
        1,
        "Text wrapped unexpectedly. The invisible URL characters were likely counted towards line width."
    );
}

#[test]
fn test_table_background_preserved_after_inline_code() {
    // BUG REPRODUCTION: Table Background
    // Inline code blocks reset background to 'default' (\x1b[49m) instead of restoring
    // the table cell background color (RGB 30,30,30).
    let mut streamer = MarkdownStreamer::new();
    streamer.set_width(100);
    let mut sink = Vec::new();

    // Fix: We must provide a Header and Separator so the third line is treated
    // as a Table Body row, where the logic we are testing resides.
    let input = "| Header |\n|---|\n| Pre `code` Post |\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);

    // The table body background color defined in markdown_streamer.rs is Rgb(30, 30, 30).
    // The ANSI sequence for this background is \x1b[48;2;30;30;30m
    let table_bg_seq = "\x1b[48;2;30;30;30m";

    // The 'reset background' sequence is \x1b[49m
    let reset_bg_seq = "\x1b[49m";

    // Find the position of "Post"
    let post_idx = raw_output
        .find("Post")
        .expect("Could not find cell content 'Post'");

    // Look at the ANSI codes immediately preceding "Post" (after the code block ends).
    // Fix: Increased look-behind window to 50 chars because the full sequence
    // (\x1b[48;...m + \x1b[39m + space) is > 20 chars long.
    let window_before_post = &raw_output[post_idx.saturating_sub(50)..post_idx];

    assert!(
        window_before_post.contains(table_bg_seq),
        "After inline code in a table, the background was not restored to table color.\nExpected sequence: {:?}\nFound context: {:?}",
        table_bg_seq,
        window_before_post
    );

    assert!(
        !window_before_post.contains(reset_bg_seq),
        "After inline code in a table, the background was incorrectly reset to default.\nFound forbidden sequence: {:?}",
        reset_bg_seq
    );
}

#[test]
fn test_math_collision_inside_code_blocks() {
    // BUG REPRODUCTION: Math Parsing
    // Math regex matches $...$ patterns inside inline code blocks (backticks),
    // corrupting shell commands like `echo "${VAR}"`.
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    // A common shell pattern that triggers the math parser
    let input = "Run `echo \"${CYAN}Hello${NC}\"` to start.\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);

    // 1. The output should still contain the dollar signs
    assert!(
        raw_output.contains("${CYAN}"),
        "The string ${{CYAN}} was modified or removed. Math parser likely consumed it."
    );

    // 2. The output should still contain the backticks (or rather, the code block formatting)
    // If the math parser runs first, it consumes the backticks inside the math match if they overlap.
    // More simply, we check that no unicode italics (which the math parser produces) exist.
    // e.g., 'C' in math italics is '𝐶' (\u{1d436}) or similar.

    // Easier check: The math parser removes the '$'. If we have '$' and '}', we are likely safe,
    // but strictly, let's verify the string looks correct.
    let cleaned = aico::console::strip_ansi_codes(&raw_output);
    assert!(
        cleaned.contains("echo \"${CYAN}Hello${NC}\""),
        "The content inside backticks was altered.\nExpected literal: echo \"${{CYAN}}Hello${{NC}}\"\nActual: {}",
        cleaned
    );
}

#[test]
fn test_header_style_preserved_after_inline_code() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    // Level 3 header in aico typically uses Cyan (Color 36)
    let input = "### Header `code` Policy\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);

    // Find the position of the text segments
    let policy_idx = raw_output
        .find(" Policy")
        .expect("Could not find cell content ' Policy'");

    // Check the ANSI codes immediately preceding " Policy" (after the code block ends).
    let window_before_policy = &raw_output[policy_idx.saturating_sub(40)..policy_idx];

    // The 'reset foreground' sequence is \x1b[39m. This is what currently breaks the header color.
    assert!(
        !window_before_policy.contains("\x1b[39m"),
        "After inline code in a header, the foreground was incorrectly reset to default terminal color.\nFound forbidden sequence: \\x1b[39m in context: {:?}",
        window_before_policy
    );

    // It should contain the color sequence for the header (Cyan = 36)
    assert!(
        window_before_policy.contains("36"),
        "Header color (Cyan/36) was not restored after inline code.\nFound context: {:?}",
        window_before_policy
    );
}

#[test]
fn test_tilde_fence_support() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    // Opening with tildes, containing backticks as content, closing with tildes
    let input = "~~~bash\n```\necho hello\n```\n~~~\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let output = String::from_utf8_lossy(&sink);
    // If working correctly, the backticks are preserved as text inside the tilde block
    assert!(output.contains("```"));
    // The closing tildes should have triggered a ResetColor (end of block)
    // ANSI code for reset is \x1b[0m
    assert!(output.contains("\x1b[0m"));
}

#[test]
fn test_fence_length_mismatch() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    // Open with 4 backticks. A 3-backtick fence inside should be ignored.
    let input = "````\n```\ncontent\n```\n````\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));

    // Normalize: Trim trailing spaces from each line
    let normalized_output: String = output
        .lines()
        .map(|line| line.trim_end())
        .collect::<Vec<_>>()
        .join("\n");

    // The internal 3-backtick fences should be visible as content, indented by 2 spaces
    assert!(
        normalized_output.contains("  ```\n  content\n  ```"),
        "Nested code fences were not correctly parsed as literal content.\nOutput:\n{}",
        normalized_output
    );
}

#[test]
fn test_backtick_info_string_constraint() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    // Info strings for backtick blocks cannot contain backticks.
    // This should be treated as normal markdown (inline code + text).
    let input = "```info`string\ncontent\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let output = String::from_utf8_lossy(&sink);
    // It should NOT have the code block background color (Rgb 30,30,30)
    // ANSI sequence: \x1b[48;2;30;30;30m
    assert!(!output.contains("48;2;30;30;30m"));
}

#[test]
fn test_inline_tilde_preservation() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    // Verify specifically that triple tildes inside inline code block are preserved
    let input = "Use `` `~~~` `` to show tildes.\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    assert!(
        output.contains("`~~~`"),
        "Inline triple tildes were corrupted. Output: {}",
        output
    );
}

#[test]
fn test_code_block_containing_tildes() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    // Test a code block (using backticks) that contains triple tildes as content.
    let input = "```markdown\nThis block contains ~~~ as text.\n```\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    assert!(
        output.contains("~~~"),
        "Triple tildes inside a backtick code block were corrupted or dropped.\nOutput: {}",
        output
    );
}

#[test]
fn test_commonmark_codespan_compliance() {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_width(200);
    streamer.set_margin(0);

    let cases = vec![
        ("`foo`", "foo"),
        ("`` foo ` bar ``", "foo ` bar"),
        ("``foo`bar``", "foo`bar"),
        ("*foo`*`", "*foo*"),
        ("` `` `", "``"),
        ("`  ``  `", " `` "),
        ("` a`", " a"),
        ("` b `", " b "),
        ("` `", " "),
        ("`  `", "  "),
        ("``\nfoo\nbar\n``", "foo bar"),
        ("`foo   bar \nbaz`", "foo   bar  baz"),
    ];

    for (input, expected) in cases {
        let mut sink = Vec::new();
        streamer.print_chunk(&mut sink, input).unwrap();
        streamer.flush(&mut sink).unwrap();

        let output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
        let actual = output.trim_end_matches('\n');

        assert_eq!(
            actual, expected,
            "CommonMark compliance failure!\nInput: {:?}\nExpected: {:?}\nActual: {:?}",
            input, expected, actual
        );
    }
}

#[test]
fn test_inline_code_background_color() {
    let mut streamer = MarkdownStreamer::new();
    let code_bg_seq = "\x1b[48;2;60;60;60m";

    let cases = vec!["Text `code` Text\n", "Text `` double code `` Text\n"];

    for input in cases {
        let mut sink = Vec::new();
        streamer
            .print_chunk(&mut sink, input)
            .expect("Write failed");
        streamer.flush(&mut sink).expect("Flush failed");

        let raw_output = String::from_utf8_lossy(&sink);

        assert!(
            raw_output.contains(code_bg_seq),
            "Inline code block for input {:?} did not have the correct background color sequence: {:?}\nOutput: {:?}",
            input,
            code_bg_seq,
            raw_output
        );
    }
}

#[test]
fn test_emphasis_flanking_rules_comprehensive() {
    let mut streamer = MarkdownStreamer::new();
    let mut sink = Vec::new();

    // 1. Whitespace Rule: "* not italic *" (Should remain literal asterisks)
    // 2. Snake Case Rule: "perform_action_now" (Underscores should remain literal)
    // 3. Intraword Asterisk: "a*b*" (Should be italic 'b')
    let input = "1. a * not italic * b\n2. perform_action_now\n3. a*b*\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let cleaned = aico::console::strip_ansi_codes(&raw_output);

    // --- Check 1: Whitespace Flanking ---
    // The current implementation blindly toggles emphasis on any '*', stripping them.
    // Spec: "a * not italic * b" -> Literal asterisks.
    assert!(
        cleaned.contains("a * not italic * b"),
        "Whitespace Flanking Failed: Asterisks were consumed/hidden in 'a * not italic * b', but should be literal."
    );
    // Ensure no ANSI italic code (\x1b[3m) was emitted for this specific line.
    // We check the raw output substring corresponding to line 1.
    if let Some(line1_end) = raw_output.find('\n') {
        let line1 = &raw_output[..line1_end];
        assert!(
            !line1.contains("\x1b[3m"),
            "Whitespace Flanking Failed: ANSI italic code found in 'a * not italic * b'."
        );
    }

    // --- Check 2: Intraword Underscores (Snake Case) ---
    // Spec: "perform_action_now" -> Literal underscores.
    assert!(
        cleaned.contains("perform_action_now"),
        "Snake_case Rule Failed: Underscores were consumed in 'perform_action_now'. Expected literal text."
    );
    // Verify no italic codes are present in the second line
    if let Some(start) = raw_output.find("2. perform") {
        if let Some(end) = raw_output[start..].find('\n') {
            let line2 = &raw_output[start..start + end];
            assert!(
                !line2.contains("\x1b[4m") && !line2.contains("\x1b[3m"),
                "Snake_case Rule Failed: ANSI underline/italic code found in 'perform_action_now'."
            );
        }
    }

    // --- Check 3: Intraword Asterisks ---
    // Spec: "a*b*" -> 'b' is emphasized.
    // The asterisk should be consumed and replaced by formatting.
    assert!(
        !cleaned.contains("a*b*"),
        "Intraword Asterisk Rule Failed: 'a*b*' asterisks remained literal. Expected them to be consumed for emphasis."
    );
    // Verify that formatting WAS applied (looking for 'a' followed immediately by italic code)
    assert!(
        raw_output.contains("a\x1b[3mb\x1b"),
        "Intraword Asterisk Rule Failed: Did not find ANSI italic sequence inside 'a*b*'."
    );
}

#[test]
fn test_list_alignment_and_nesting_comprehensive() {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = concat!(
        "- Bullet Item\n",
        "  Indented Continuation\n", // Case A: Explicit Indent (PASSES currently)
        "- Lazy Parent\n",
        "Lazy Continuation\n" // Case B: Lazy/No Indent (FAILS currently)
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    let lines: Vec<&str> = raw_output.lines().collect();

    // Case A: Explicit Indent (Green)
    let indented_cont = lines.get(1).expect("Missing indented line");
    assert!(
        indented_cont.starts_with("  Indented"),
        "Explicit Indent Failed."
    );

    // Case B: Lazy Continuation (Red)
    // CommonMark: "Lazy Continuation" should wrap/align with "Lazy Parent".
    // Current Streamer: Renders at margin (0 spaces).
    let lazy_cont = lines.get(3).expect("Missing lazy line");

    // We expect the renderer to handle wrapping/alignment logic,
    // effectively treating this as part of the bullet item.
    // NOTE: Since the current implementation treats this as a separate paragraph block,
    // checking that it starts with "  " (2 spaces) will fail.
    assert!(
        lazy_cont.starts_with("  Lazy"),
        "Lazy Continuation Failed: Text without indent should align with list item.\nActual: '{:?}'",
        lazy_cont
    );
}

#[test]
fn test_rule_01_asterisk_open() {
    // Rule 1: A single * character can open emphasis iff it is part of a left-flanking delimiter run.

    // Example 1: Basic valid emphasis
    check(
        "*foo bar*",
        format!("{}foo bar{}", ITALIC, ITALIC_OFF).as_str(),
    );

    // Example 2: Followed by whitespace (Not left-flanking) -> Literal
    check("a * foo bar*", "a * foo bar*");

    // Example 3: Preceded by alphanum, followed by punct (Not left-flanking) -> Literal
    check("a*\"foo\"*", "a*\"foo\"*");

    // Example 4: Surrounded by spaces -> Literal
    check("* a *", "* a *");

    // Example 5: Intraword emphasis (Allowed for *)
    check(
        "foo*bar*",
        format!("foo{}bar{}", ITALIC, ITALIC_OFF).as_str(),
    );

    // Example 6: Intraword numbers
    check("5*6*78", format!("5{}6{}78", ITALIC, ITALIC_OFF).as_str());
}

#[test]
fn test_rule_02_underscore_open() {
    // Rule 2: _ can open emphasis iff left-flanking AND (not right-flanking OR preceded by punctuation)
    // Note: Streamer maps _ to UNDERLINE (\x1b[4m)

    // Example 1: Basic valid
    check(
        "_foo bar_",
        format!("{}foo bar{}", UNDERLINE, UNDERLINE_OFF).as_str(),
    );

    // Example 2: Followed by whitespace -> Literal
    check("_ foo bar_", "_ foo bar_");

    // Example 3: Preceded by alphanum, followed by punct -> Literal
    check("a_\"foo\"_", "a_\"foo\"_");

    // Example 4: Intraword forbidden for _
    check("foo_bar_", "foo_bar_");
    check("5_6_78", "5_6_78");
    check("пристаням_стремятся_", "пристаням_стремятся_");

    // Example 5: Right-flanking and Left-flanking mismatch
    check("aa_\"bb\"_cc", "aa_\"bb\"_cc");

    // Example 6: Preceded by punctuation (Allowed)
    check(
        "foo-_(bar)_",
        format!("foo-{}(bar){}", UNDERLINE, UNDERLINE_OFF).as_str(),
    );
}

#[test]
fn test_rule_03_asterisk_close() {
    // Rule 3: * can close iff right-flanking

    // Example 1: Mismatched delimiters
    check("_foo*", "_foo*");

    // Example 2: Preceded by whitespace -> Literal
    check("*foo bar *", "*foo bar *");

    // Example 3: Preceded by punct, followed by alphanum -> Literal
    check("*(*foo)", "*(*foo)");

    // Example 4: Intraword allowed
    check(
        "*foo*bar",
        format!("{}foo{}bar", ITALIC, ITALIC_OFF).as_str(),
    );
}

#[test]
fn test_rule_04_underscore_close() {
    // Rule 4: _ can close iff right-flanking AND (not left-flanking OR followed by punctuation)

    // Example 1: Preceded by whitespace
    check("_foo bar _", "_foo bar _");

    // Example 2: Preceded by punct, followed by alphanum
    check("_(_foo)", "_(_foo)");

    // Example 3: Nested _ inside _ (Allowed if punctuation boundaries exist)
    // _(_foo_)_ -> (foo) wrapped in outer, then inner?
    // Spec: <em>(<em>foo</em>)</em>
    // Implementation: U + ( + U + foo + U_X + ) + U_X
    check(
        "_(_foo_)_",
        format!(
            "{}({}foo{}){}",
            UNDERLINE, UNDERLINE, UNDERLINE_OFF, UNDERLINE_OFF
        )
        .as_str(),
    );

    // Example 4: Intraword forbidden
    check("_foo_bar", "_foo_bar");
    check(
        "_foo_bar_baz_",
        format!("{}foo_bar_baz{}", UNDERLINE, UNDERLINE_OFF).as_str(),
    );

    // Example 5: Followed by punctuation (Allowed)
    check(
        "_(bar)_.",
        format!("{}(bar){}.", UNDERLINE, UNDERLINE_OFF).as_str(),
    );
}

#[test]
fn test_rule_05_double_asterisk_open() {
    // Rule 5: ** opens strong (Bold)

    check(
        "**foo bar**",
        format!("{}foo bar{}", BOLD, BOLD_OFF).as_str(),
    );
    check("** foo bar**", "** foo bar**"); // Space -> Literal
    check("a**\"foo\"**", "a**\"foo\"**"); // Intraword punct -> Literal
    check("foo**bar**", format!("foo{}bar{}", BOLD, BOLD_OFF).as_str()); // Intraword allowed
}

#[test]
fn test_rule_06_double_underscore_open() {
    // Rule 6: __ opens strong (Bold)

    check(
        "__foo bar__",
        format!("{}foo bar{}", BOLD, BOLD_OFF).as_str(),
    );
    check("__ foo bar__", "__ foo bar__");
    check("foo__bar__", "foo__bar__"); // Intraword forbidden
    check("5__6__78", "5__6__78");
    check(
        "foo-__(bar)__",
        format!("foo-{}(bar){}", BOLD, BOLD_OFF).as_str(),
    ); // Punctuation -> Allowed
}

#[test]
fn test_rule_09_nesting() {
    // Rule 9: Emphasis inside Emphasis / Mixed

    // *foo [bar](/url)* -> We treat link as literal text for this check unless we implement link parsing logic
    // check("*foo [bar](/url)*", format!("{}foo [bar](/url){}", ITALIC, ITALIC_OFF).as_str());

    // _foo __bar__ baz_ -> U + foo + B + bar + B_X + baz + U_X
    check(
        "_foo __bar__ baz_",
        format!(
            "{}foo {}bar{} baz{}",
            UNDERLINE, BOLD, BOLD_OFF, UNDERLINE_OFF
        )
        .as_str(),
    );

    // *foo **bar** baz*
    check(
        "*foo **bar** baz*",
        format!("{}foo {}bar{} baz{}", ITALIC, BOLD, BOLD_OFF, ITALIC_OFF).as_str(),
    );

    // ***foo** bar* -> * + **foo** + bar + * -> I + B + foo + B_X + bar + I_X
    check(
        "***foo** bar*",
        format!("{}{}foo{} bar{}", ITALIC, BOLD, BOLD_OFF, ITALIC_OFF).as_str(),
    );

    // *foo **bar***
    check(
        "*foo **bar***",
        format!("{}foo {}bar{}{}", ITALIC, BOLD, BOLD_OFF, ITALIC_OFF).as_str(),
    );
}

#[test]
fn test_rule_11_escaping_asterisk() {
    // Rule 11: Escaped * should be literal

    check("foo \\*bar\\*", "foo *bar*");
    check("foo * bar", "foo * bar"); // Literal standalone

    // Mismatched: ***foo** -> * + **foo** -> * + B + foo + B_X ?
    // Spec: *<strong>foo</strong>
    check("***foo**", format!("*{}foo{}", BOLD, BOLD_OFF).as_str());
}

#[test]
fn test_rule_12_escaping_underscore() {
    // Rule 12: Escaped _ should be literal

    check("foo \\_bar\\_", "foo _bar_");
}

#[test]
fn test_rule_14_precedence() {
    // Rule 14: ***foo*** -> <em><strong>foo</strong></em>
    // Spec prefers Italics-outer: I + B + foo + B_X + I_X
    check(
        "***foo***",
        format!("{}{}foo{}{}", ITALIC, BOLD, BOLD_OFF, ITALIC_OFF).as_str(),
    );
}

#[test]
fn test_rule_16_overlap() {
    // Rule 16: **foo **bar baz** -> **foo <strong>bar baz</strong>
    check(
        "**foo **bar baz**",
        format!("**foo {}bar baz{}", BOLD, BOLD_OFF).as_str(),
    );
}

#[test]
fn test_list_integrity_with_interleaved_code_blocks() {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_width(80);
    streamer.set_margin(0);

    let mut sink = Vec::new();
    let input = concat!(
        "1. Step One\n",
        "   ```bash\n",
        "   echo 'inside code'\n",
        "   ```\n",
        "2. Step Two\n"
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let cleaned_output = aico::console::strip_ansi_codes(&raw_output);
    let lines: Vec<&str> = cleaned_output.lines().collect();

    // 1. Check Code Indentation
    let code_line = lines.iter().find(|l| l.contains("inside code")).unwrap();
    assert!(
        code_line.starts_with("  "),
        "Code block lost indentation context."
    );

    // 2. Check Second Item Integrity
    let item_two_line = lines.iter().find(|l| l.contains("Step Two")).unwrap();
    assert!(
        item_two_line.starts_with("2. "),
        "Second list item lost alignment."
    );

    // 3. Check ANSI Coloring (Yellow list item)
    assert!(
        raw_output.contains("\u{1b}[38;5;11m2."),
        "Second list item lost specific styling (Yellow), indicating context reset."
    );
}

#[test]
fn test_list_with_same_line_code_fence() {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = concat!("1. ```ruby\n", "   1+1\n", "   ```\n", "2. Next\n");

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw = String::from_utf8_lossy(&sink);
    let clean = strip_ansi_codes(&raw);
    let lines: Vec<&str> = clean.lines().collect();

    // Check 1: First line is just the bullet (Fence forced newline)
    assert_eq!(
        lines[0].trim(),
        "1.",
        "First line should be just the list marker"
    );

    // Check 2: Code content exists and is indented
    let code_content = lines
        .iter()
        .find(|l| l.contains("1+1"))
        .expect("Code content missing");
    assert!(
        code_content.contains("1+1"),
        "Code content should be rendered"
    );

    // Check 3: Next item is correct
    let next_item = lines
        .iter()
        .find(|l| l.contains("Next"))
        .expect("Item 2 missing");
    assert!(next_item.starts_with("2. "), "Item 2 should be at root");

    // Check 4: No inline code artifacts
    assert!(
        !clean.ends_with("```ruby"),
        "Should not dump buffer at the end"
    );
}
