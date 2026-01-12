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
