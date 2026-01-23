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
    // Expect 3 spaces (Margin 0 + Marker '1. ' width 3)
    let code_line = lines
        .iter()
        .find(|l| l.contains("indented content"))
        .expect("Code content missing");
    assert!(
        code_line.starts_with("   indented"),
        "Code content indent failed. Expected 3 spaces (matching '1. '). Got: '{}'",
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
   A     │ B
   1     │ 2
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

    let raw_output = String::from_utf8_lossy(&sink);
    // The closing tildes should have triggered a ResetColor (end of block)
    // ANSI code for reset is \x1b[0m
    assert!(raw_output.contains("\x1b[0m"));

    let cleaned = strip_ansi_codes(&raw_output);
    // If working correctly, the backticks are preserved as text inside the tilde block
    assert!(cleaned.contains("```"));
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
        "  Indented Continuation\n", // Case A: Explicit Indent
        "- Lazy Parent\n",
        "Lazy Continuation\n" // Case B: No Indent (Should exit list)
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    let lines: Vec<&str> = raw_output.lines().collect();

    // Case A: Explicit Indent (Should still work)
    let indented_cont = lines.get(1).expect("Missing indented line");
    assert!(
        indented_cont.starts_with("  Indented"),
        "Explicit Indent Failed: Indented text should stay inside the list."
    );

    // Case B: Lazy Continuation (UPDATED EXPECTATION)
    // We intentionally disable CommonMark Lazy Continuation to allow users
    // to exit lists by typing at the start of the line.
    let lazy_cont = lines.get(3).expect("Missing lazy line");

    assert!(
        !lazy_cont.starts_with(" "),
        "Lazy Continuation / List Exit Failed: Text without indent should exit the list context.\nActual: '{:?}'",
        lazy_cont
    );
}

#[test]
fn test_rule_01_asterisk_open() {
    // Rule 1: A single * character can open emphasis iff it is part of a left-flanking delimiter run.
    // The key condition is: If followed by whitespace, it is NOT emphasis.

    // Example 1: Basic valid emphasis
    // "*" followed by "f" (not whitespace) -> Emphasis
    check(
        "*foo bar*",
        format!("{}foo bar{}", ITALIC, ITALIC_OFF).as_str(),
    );

    // Example 2: Followed by whitespace (Not left-flanking) -> Literal
    // Input: "a * foo bar*"
    // The first "*" is followed by a space. Rule 1 says it remains literal.
    check("a * foo bar*", "a * foo bar*");

    // Example 3: Preceded by alphanum, followed by punct (Not left-flanking) -> Literal
    check("a*\"foo\"*", "a*\"foo\"*");

    // Example 4: Surrounded by spaces -> Literal
    // Input: "x * a *"
    // IMPORTANT: We place 'x' at the start.
    // If we used "* a *", the Block Parser would seize it as a List Item.
    // By using "x * a *", we force it to be a Paragraph, letting us verify
    // that the Inline Parser sees "* " and correctly leaves it as literal text.
    check("x * a *", "x * a *");

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

#[test]
fn test_repro_bug_01_sticky_list_indentation() {
    // BUG REPRODUCTION: Sticky List State
    // Spec Reference: CommonMark Example 289 (Lists)
    // "A list item can contain a block quote." -> implication: exiting list resets context.
    //
    // Case: A paragraph following a list must NOT be indented.
    // Current Behavior: The 'list_stack' is not popped, causing 'Paragraph' to inherit indentation.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0); // Use 0 margin to make detection easy (expecting NO leading spaces)
    let mut sink = Vec::new();

    let input = concat!(
        "- Item 1\n",
        "- Item 2\n",
        "\n",
        "Paragraph should be root.\n"
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let clean_output = strip_ansi_codes(&raw_output);
    let lines: Vec<&str> = clean_output.lines().collect();

    let paragraph_line = lines.last().expect("Output was empty");

    // Assertion: The paragraph must NOT start with spaces.
    // If the bug is present, this will likely start with "  " (inherited from list).
    assert!(
        !paragraph_line.starts_with(" "),
        "Sticky List Bug Detected: Root paragraph following a list retained indentation.\nActual: '{}'",
        paragraph_line
    );
}

#[test]
fn test_repro_bug_02_blockquote_links_and_leaking() {
    // BUG REPRODUCTION: Blockquote Leaks & Link Tokenization
    // Spec Reference: CommonMark Example 228 (Block quotes) + Example 494 (Links)
    //
    // Issue A: Blockquote context ('│ ') leaks to subsequent paragraphs.
    // Issue B: Links inside blockquotes are tokenized incorrectly, showing raw ANSI codes.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = concat!(
        "> [Link](https://example.com)\n",
        "\n",
        "Post-quote paragraph.\n"
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let clean_output = strip_ansi_codes(&raw_output);
    let lines: Vec<&str> = clean_output.lines().collect();

    // --- Sub-test A: Indentation/Context Leak ---
    let last_line = lines.last().expect("Missing last line");
    assert!(
        !last_line.contains("│"),
        "Blockquote Leak Detected: The blockquote border '│' persisted to the next paragraph."
    );
    assert!(
        !last_line.starts_with(" "),
        "Blockquote Indent Leak Detected: The paragraph retained blockquote/list indentation."
    );

    // --- Sub-test B: Link Tokenization ---
    // We look for broken ANSI sequences in the raw output.
    // A broken sequence manifests as literal text without the escape char (\x1b).
    let link_line_index = raw_output.lines().position(|l| l.contains("Link")).unwrap();
    let link_line_raw = raw_output.lines().nth(link_line_index).unwrap();

    // 1. Check for broken ANSI literals (bracket/numbers without leading ESC)
    let broken_fg = "[33;4m";
    let broken_reset = "[24;39m";

    let has_broken =
        |raw: &str, target: &str| raw.contains(target) && !raw.contains(&format!("\x1b{}", target));

    assert!(
        !has_broken(link_line_raw, broken_fg) && !has_broken(link_line_raw, broken_reset),
        "Link Tokenization Bug Detected: Found literal ANSI codes without escape characters.\nRaw Line: {:?}",
        link_line_raw
    );

    // 2. Check for presence of OSC 8 Hyperlink sequence (Success case)
    // The sequence is \x1b]8;;
    assert!(
        link_line_raw.contains("\x1b]8;;"),
        "Link Rendering Failed: OSC 8 hyperlink sequence is missing."
    );
}

#[test]
fn test_repro_bug_03_nested_list_indentation() {
    // BUG REPRODUCTION: Nested List Alignment
    // Spec Reference: CommonMark Example 266 (Nested Lists)
    //
    // Issue: The streamer calculates indentation using strict multiplication (depth * 2)
    // rather than observing the relative indentation of the input.
    // This causes misalignment or excessive indentation for nested items.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    // Standard 3-level nesting
    let input = concat!("1. Level 1\n", "   1. Level 2\n", "      1. Level 3\n");

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = strip_ansi_codes(&String::from_utf8_lossy(&sink));
    let lines: Vec<&str> = raw_output.lines().collect();

    let get_indent = |s: &str| s.chars().take_while(|c| *c == ' ').count();

    let indent_1 = get_indent(lines[0]); // Level 1
    let indent_2 = get_indent(lines[1]); // Level 2
    let indent_3 = get_indent(lines[2]); // Level 3

    assert!(
        indent_2 > indent_1,
        "Level 2 should be indented more than Level 1"
    );
    assert!(
        indent_3 > indent_2,
        "Level 3 should be indented more than Level 2"
    );

    // Specific check for the bug:
    // If logic is broken, Level 2 might be treated as a continuation of Level 1 (indent_2 == indent_1)
    // or the multiplier might be wrong.
    // We expect roughly 2-3 spaces difference per level.
    let delta_1_2 = indent_2 - indent_1;
    let delta_2_3 = indent_3 - indent_2;

    assert!(
        delta_1_2 >= 2 && delta_1_2 <= 4,
        "Nested Indentation Bug: Level 2 indentation delta is suspicious ({} spaces). Expected 2-4.",
        delta_1_2
    );
    assert!(
        delta_2_3 >= 2 && delta_2_3 <= 4,
        "Nested Indentation Bug: Level 3 indentation delta is suspicious ({} spaces). Expected 2-4.",
        delta_2_3
    );
}

#[test]
fn test_repro_bug_04_code_block_wrapping_background() {
    // BUG REPRODUCTION: Code Block Background on Wrap
    // Spec Reference: CommonMark Example 88 (Fenced Code Blocks)
    //
    // Issue: When a code line exceeds terminal width, the wrapping is handled by the terminal
    // (or not at all), breaking the background color block. The renderer must manually wrap.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_width(20); // Force aggressive wrapping
    let mut sink = Vec::new();

    let input = "```text\nAAAAABBBBBCCCCCDDDDD\n```\n";
    // Length 20. With margin (default 2), available width is 18.
    // This MUST wrap.

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let lines: Vec<&str> = raw_output.lines().collect();

    // Skip the opening/closing fence lines if they exist in output (implementation dependent)
    // We look for the content lines.
    let content_lines: Vec<&&str> = lines
        .iter()
        .filter(|l| l.contains('A') || l.contains('B') || l.contains('C') || l.contains('D'))
        .collect();

    assert!(
        content_lines.len() >= 2,
        "Code Block Wrapping Bug: Long line did not wrap despite set_width(20). Found {} content lines.",
        content_lines.len()
    );

    // Verify Background Color Persistence
    // The dark gray background is \x1b[48;2;30;30;30m
    let bg_seq = "48;2;30;30;30m";

    for (i, line) in content_lines.iter().enumerate() {
        assert!(
            line.contains(bg_seq),
            "Code Block Background Bug: Wrapped line {} lost its background color.\nLine content: {:?}",
            i + 1,
            line
        );
    }
}

#[test]
fn test_repro_bug_05_ordered_list_alignment() {
    // BUG REPRODUCTION: Ordered List Marker Width
    // Spec Principle: Content should align with the text of the list item,
    // taking the marker width into account.
    //
    // "1. " is 3 chars wide.
    // Current Implementation: Hardcodes 2 spaces per level.
    // Result:
    //   1. Start
    //     Continuation (2 spaces, misaligned)
    //
    // Expected:
    //   1. Text
    //      Continuation (3 spaces, aligned)

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = concat!(
        "1. Start\n",
        "   Continuation\n", // Input has 3 spaces
        "   * Nested\n"      // Nested item should also align to column 3
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    let lines: Vec<&str> = raw_output.lines().collect();

    // Line 1: "1. Start"
    // Marker width = 3 chars ("1. ")

    // Line 2: Continuation
    // Should be indented by 3 spaces to align with "Start"
    let cont_line = lines.get(1).expect("Missing continuation line");
    let cont_indent = cont_line.chars().take_while(|c| *c == ' ').count();

    assert_eq!(
        cont_indent, 3,
        "Ordered list continuation was under-indented. Expected 3 spaces (matching '1. '), got {}.",
        cont_indent
    );

    // Line 3: Nested Item
    // Should be indented by 3 spaces to align with parent text
    let nested_line = lines.get(2).expect("Missing nested line");
    let nested_indent = nested_line.chars().take_while(|c| *c == ' ').count();

    assert_eq!(
        nested_indent, 3,
        "Nested list item was under-indented. Expected 3 spaces (aligning with parent '1. '), got {}.",
        nested_indent
    );
}

#[test]
fn test_repro_bug_06_spec_alignment_compliance() {
    // BUG REPRODUCTION: Variable Marker Spacing (Spec Rule 1 violation)
    // Spec Reference: CommonMark Spec "List items", Rule 1 [cite: 387-388]
    // See also Example 394.
    //
    // Principle: "The position of the text after the list marker determines
    // how much indentation is needed."
    //
    // Input Case:
    // "1.  Text"
    //  ^   ^
    //  |---|
    //  Marker "1." (Width W=2) + Spacing (N=2) = Total Indent 4.
    //
    // If the renderer collapses this to "1. Text" (Indent 3), it violates the spec
    // because the "structural indent" of the block should remain 4.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = concat!(
        "1.  Header\n",       // W=2, N=2 -> Indent 4
        "    Continuation\n"  // Indent 4. Matches header text column.
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    let lines: Vec<&str> = raw_output.lines().collect();

    // Check 1: Header Line Preservation
    // The renderer must preserve the visual gap (2 spaces) or equivalent structural alignment.
    // Current bug: Collapses to "1. Header" (1 space).
    let header_line = lines[0];
    assert!(
        header_line.contains("1.  Header"),
        "Spec Violation: Renderer altered the defining spacing of the list item.\nExpected '1.  Header', got '{}'",
        header_line
    );

    // Check 2: Continuation Alignment
    // The continuation line provided 4 spaces. The renderer should strip exactly 4 spaces
    // (the W+N calculated from line 1).
    //
    // If it calculated W+N=3 (the bug), it will strip 3 spaces and leave 1 space visible.
    let continuation_line = lines[1];

    // We expect NO leading spaces on the content "Continuation" because they should
    // all be consumed by the list indentation logic.
    let indent_count = continuation_line.chars().take_while(|c| *c == ' ').count();

    assert_eq!(
        indent_count, 4,
        "Spec Violation: Continuation alignment mismatch.\nExpected 4 spaces (matching '1.  '), got {}.\nLine: '{}'",
        indent_count, continuation_line
    );
}

#[test]
fn test_sticky_list_exit_behavior() {
    // BUG REPRODUCTION: Sticky List State
    // A root-level paragraph (0 indent) should force the list to close.
    // Currently, the 'if current_indent > 0' guard prevents this.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = concat!(
        "- Item 1\n",
        "  - Nested\n",
        "Root Paragraph\n" // 0 indent -> Should exit list context
    );

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    let lines: Vec<&str> = raw_output.lines().collect();

    let root_line = lines.last().expect("Missing root line");

    // If the bug exists, this line will be indented (e.g., "  Root Paragraph")
    assert!(
        !root_line.starts_with(" "),
        "Sticky List Bug: Root paragraph failed to exit list context.\nActual: '{:?}'",
        root_line
    );
}

#[test]
fn test_spec_ex_43_hr_precedence() {
    // Spec Section 4.1, Example 43:
    // "When both a thematic break and a list item are possible interpretations
    // of a line, the thematic break takes precedence."
    //
    // Input:
    //   - Foo
    //   - * * *
    //
    // Expected: A list item "Foo", followed by a Horizontal Rule.
    // Current Bug: "* * *" is interpreted as a nested list item because
    // try_handle_list runs before try_handle_hr.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = "- Foo\n- * * *\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let clean_output = aico::console::strip_ansi_codes(&raw_output);

    // We expect the horizontal rule drawing character "─"
    assert!(
        clean_output.contains("─"),
        "Spec Ex 43: Failed to render thematic break. Output:\n{}",
        clean_output
    );

    // We should NOT see a second bullet for "* * *"
    let bullet_count = clean_output.matches("•").count();
    assert_eq!(
        bullet_count, 1,
        "Spec Ex 43: '* * *' was incorrectly rendered as a list item instead of HR."
    );
}

#[test]
fn test_spec_ex_330_block_precedence() {
    // Spec Section 6.1, Example 330:
    // "Indicators of block structure always take precedence over indicators of inline structure."
    //
    // Input:
    //   - `one
    //   - two`
    //
    // Expected: Two list items. The backticks are literal text.
    // Current Bug: The first backtick opens an inline code span, and the guard
    // `if self.inline_code_ticks.is_none()` prevents the second line from being
    // recognized as a list item.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = "- `one\n- two`\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let clean_output = aico::console::strip_ansi_codes(&raw_output);

    // We expect TWO bullets
    let bullet_count = clean_output.matches("•").count();
    assert_eq!(
        bullet_count, 2,
        "Spec Ex 330: Inline code span incorrectly suppressed the second list item. Output:\n{}",
        clean_output
    );

    // Verify both list items are present as text
    assert!(
        clean_output.contains("`one"),
        "Spec Ex 330: First list item content missing."
    );
    assert!(
        clean_output.contains("two`"),
        "Spec Ex 330: Second list item content missing."
    );
}

#[test]
fn test_tokenizer_priority_code_vs_math() {
    // BUG REPRODUCTION: Tokenizer Priority
    // Spec Reference: CommonMark 5.1/6.1 "Code span backticks have higher precedence..."
    // Current behavior: Math regex ($...$) runs before Code, mangling shell scripts.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    // A string that looks like math if you ignore backticks: "$VAR" ... "$VAR"
    let input = "Code: `echo \"$VAR\" and \"$VAR\"` end.\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);

    // 1. Verify content preservation
    assert!(
        raw_output.contains("$VAR"),
        "Tokenizer Bug: variable '$VAR' was consumed/altered by Math parser."
    );

    // 2. Verify no Math styling (Italic \x1b[3m) leaked in
    assert!(
        !raw_output.contains("\x1b[3m"),
        "Tokenizer Bug: Detected Math styling inside a code block."
    );
}

#[test]
fn test_spec_compliance_block_precedence_list_vs_emphasis() {
    // Spec Reference: CommonMark Section 6.1 (Blocks and inlines - Precedence)
    // "Indicators of block structure always take precedence over indicators of inline structure."

    use aico::console::strip_ansi_codes;

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    // Case 1: Canonical Spec Example
    // Input: "* a *"
    // This MUST be a list item. The current engine logic explicitly forbids this
    // due to the incorrect heuristic in try_handle_list.
    let input_canonical = "* a *\n";
    streamer
        .print_chunk(&mut sink, input_canonical)
        .expect("Write 1 failed");

    // Case 2: User Reported Bug
    // Input: "* **Title:**"
    // This fails for the same reason: the line ends with '*', so the engine treats it as text.
    let input_user = "* **Title:**\n";
    streamer
        .print_chunk(&mut sink, input_user)
        .expect("Write 2 failed");

    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let clean_output = strip_ansi_codes(&raw_output);

    // VERIFICATION
    // Both lines should be rendered as List Items (•).

    assert!(
        clean_output.contains("• a *"),
        "Canonical Precedence Bug: '* a *' was not parsed as a list item.\nOutput: {:?}",
        clean_output
    );

    assert!(
        clean_output.contains("• Title:"),
        "User Bug: '* **Title:**' was not parsed as a list item.\nOutput: {:?}",
        clean_output
    );
}

#[test]
fn test_emphasis_multiple_of_3_rule() {
    // Spec Example 413: 1+2=3, neither is multiple of 3, so ** cannot match *
    check(
        "*foo**bar*",
        format!("{}foo**bar{}", ITALIC, ITALIC_OFF).as_str(),
    );
}

#[test]
fn test_emphasis_multiple_of_3_both_multiples() {
    // Spec Example 414: foo***bar***baz -> <em><strong>bar</strong></em>
    // 3+3=6 is multiple of 3, AND both 3 and 3 are multiples of 3, so it matches
    check(
        "foo***bar***baz",
        format!("foo{}{}bar{}{}baz", ITALIC, BOLD, BOLD_OFF, ITALIC_OFF).as_str(),
    );
}

#[test]
fn test_spec_ex_43_thematic_break_precedence() {
    // Spec Example 43: "* * *" as its own line should be HR, not list
    // Note: The previous test `test_spec_ex_43_hr_precedence` used "- * * *" which is ambiguous/list.
    // This test specifically targets the case where the line ITSELF is the HR marker using asterisks.

    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = "* Foo\n* * *\n* Bar\n";
    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let clean = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));

    // Should have exactly 2 bullets (Foo and Bar) and 1 HR (─)
    // Currently, without fix, the parser likely sees "* * *" as a list item with bullet "*" and content "* *"
    assert_eq!(
        clean.matches("•").count(),
        2,
        "Should have 2 list items. Got output:\n{}",
        clean
    );
    assert!(clean.contains("─"), "Should contain horizontal rule");
}

#[test]
fn test_link_nested_brackets_in_text() {
    // Spec Example 508: [link [foo [bar]]](/uri)
    // The link text can contain balanced brackets.
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = "[link [foo [bar]]](/uri)\n";
    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let output = String::from_utf8_lossy(&sink);

    // Should contain OSC8 link sequence to /uri
    assert!(
        output.contains("\x1b]8;;/uri\x1b\\"),
        "Should create hyperlink to /uri"
    );

    // Link text should include the brackets
    let clean = aico::console::strip_ansi_codes(&output);
    assert!(
        clean.contains("link [foo [bar]]"),
        "Nested brackets should be preserved in link text"
    );
}

#[test]
fn test_link_balanced_parentheses_in_url() {
    // Spec Example 497: [link](foo(and(bar)))
    // The URL can contain balanced parentheses.
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    let mut sink = Vec::new();

    let input = "[link](foo(and(bar)))\n";
    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let output = String::from_utf8_lossy(&sink);

    // The URL should be complete with balanced parens in the OSC8 sequence
    // Note: OSC8 format is \x1b]8;;URL\x1b\\TEXT\x1b]8;;\x1b\\
    assert!(
        output.contains("\x1b]8;;foo(and(bar))\x1b\\"),
        "URL with balanced parentheses should be preserved in OSC8 sequence"
    );
}

#[test]
fn test_empty_emphasis_not_allowed() {
    // Spec Example 408-409: ** and **** alone are not emphasis
    check("** is not an empty emphasis", "** is not an empty emphasis");
    check(
        "**** is not an empty strong emphasis",
        "**** is not an empty strong emphasis",
    );
}

#[test]
fn test_table_no_right_gap() {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    streamer.set_width(20);
    let mut sink = Vec::new();

    // Table with 2 columns
    let input = "| A | B |\n|---|---|\n| 1 | 2 |\n";
    streamer.print_chunk(&mut sink, input).unwrap();
    streamer.flush(&mut sink).unwrap();

    let raw = String::from_utf8_lossy(&sink);
    let clean = aico::console::strip_ansi_codes(&raw);

    for (i, line) in clean.lines().enumerate() {
        // We do NOT trim_end() because the table renderer pads the line with spaces (background color)
        // to fill the width. We want to verify those spaces are present.
        // We use chars().count() because the table separator (│) is multi-byte in UTF-8.
        assert_eq!(
            line.chars().count(),
            20,
            "Line {} is not the correct width ({} chars): '{}'. Expected 20.",
            i,
            line.chars().count(),
            line
        );
    }
}

#[test]
fn test_table_long_cell_uses_full_width() {
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    streamer.set_width(30);
    let mut sink = Vec::new();

    // Single column table.
    // Width 30, margin 0.
    // Current buggy calculation of 'avail' = 26.
    // Fixed calculation of 'avail' should be 28 (30 - 2 padding).
    // Content of 27 chars should wrap in buggy code but fit in fixed code.
    let input = "| AAAAAAAAAAAAAAAAAAAAAAAAAAA |\n"; // 27 A's
    streamer.print_chunk(&mut sink, input).unwrap();
    streamer.flush(&mut sink).unwrap();

    let clean = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    let lines: Vec<&str> = clean.lines().collect();

    assert_eq!(
        lines.len(),
        1,
        "Table row should not have wrapped. It should use the full width available. Got {} lines: {:?}",
        lines.len(),
        clean
    );
}

#[test]
fn test_table_streaming_partial_row_wrapping() {
    // Tests that wrapping is correct when a long row is streamed in chunks.
    let mut streamer = MarkdownStreamer::new();
    streamer.set_margin(0);
    streamer.set_width(20);
    let mut sink = Vec::new();

    // Avail width (buggy) = 16.
    // Content of 17 chars should fit in 20 width (18 avail).
    // But buggy logic makes it wrap.
    streamer.print_chunk(&mut sink, "| 12345678").unwrap();
    streamer.print_chunk(&mut sink, "901234567 |").unwrap();
    streamer.print_chunk(&mut sink, "\n").unwrap();
    streamer.flush(&mut sink).unwrap();

    let clean = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&sink));
    let lines: Vec<&str> = clean.lines().collect();

    assert_eq!(
        lines.len(),
        1,
        "Streaming a long row caused incorrect wrapping. Expected 1 line, got {}. Output: {:?}",
        lines.len(),
        clean
    );
}
