use aico::console::strip_ansi_codes;
use aico::ui::markdown_streamer::MarkdownStreamer;

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

    let input = "1. Item One\n```\ncode\n```\n2. Item Two\n";

    streamer
        .print_chunk(&mut sink, input)
        .expect("Write failed");
    streamer.flush(&mut sink).expect("Flush failed");

    let raw_output = String::from_utf8_lossy(&sink);
    let clean_output = strip_ansi_codes(&raw_output);

    let expected = "  1. Item One\n  code\n\n  2. Item Two\n";

    let normalized_output: String = clean_output
        .lines()
        .map(|line| line.trim_end())
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";

    assert_eq!(
        normalized_output, expected,
        "List numbering should continue after code block, but reset occurred"
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
