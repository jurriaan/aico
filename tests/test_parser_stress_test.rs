use aico::diffing::parser::StreamParser;
use aico::models::DisplayItem;
use proptest::prelude::*;
use std::collections::HashMap;
use std::path::Path;
use tempfile::tempdir;

// =============================================================================
// CONSTANTS
// =============================================================================

const TEST_FILENAME: &str = "src/main.rs";
const ORIGINAL_CONTENT: &str = "fn main() {\n    println!(\"Hello\");\n}\n";

// =============================================================================
// HELPERS
// =============================================================================

fn create_baseline() -> HashMap<String, String> {
    let mut baseline = HashMap::new();
    baseline.insert(TEST_FILENAME.to_string(), ORIGINAL_CONTENT.to_string());
    baseline
}

#[derive(Debug, Clone, PartialEq)]
struct ParserResult {
    diff: String,
    items: Vec<DisplayItem>,
    warnings: Vec<String>,
}

fn normalize_items(items: Vec<DisplayItem>) -> Vec<DisplayItem> {
    let mut merged = Vec::new();
    for item in items {
        if let (Some(DisplayItem::Markdown(last)), DisplayItem::Markdown(next)) =
            (merged.last_mut(), &item)
        {
            last.push_str(next);
        } else {
            merged.push(item);
        }
    }
    merged
}

fn run_parser_whole(baseline: &HashMap<String, String>, input: &str) -> ParserResult {
    let mut parser = StreamParser::new(baseline);
    parser.feed(input);
    let (diff, items, warnings) = parser.final_resolve(Path::new("."));
    ParserResult {
        diff,
        items: normalize_items(items),
        warnings,
    }
}

fn run_parser_char_by_char(baseline: &HashMap<String, String>, input: &str) -> ParserResult {
    let mut parser = StreamParser::new(baseline);
    let mut accumulated_items = Vec::new();
    let mut accumulated_warnings = Vec::new();

    for c in input.chars() {
        let yields = parser.parse_and_resolve(&c.to_string(), Path::new("."));
        accumulated_warnings.extend(parser.collect_warnings(&yields));
        for y in yields {
            if let Some(di) = y.to_display_item(true) {
                accumulated_items.push(di);
            }
        }
    }

    let (diff, mut final_items, final_warnings) = parser.final_resolve(Path::new("."));
    accumulated_items.append(&mut final_items);
    accumulated_warnings.extend(final_warnings);

    ParserResult {
        diff,
        items: normalize_items(accumulated_items),
        warnings: accumulated_warnings,
    }
}

fn run_parser_random_chunks(
    baseline: &HashMap<String, String>,
    input: &str,
    chunk_sizes: &[usize],
) -> ParserResult {
    let mut parser = StreamParser::new(baseline);
    let bytes = input.as_bytes();
    let mut pos = 0;
    let mut chunk_idx = 0;

    // We must accumulate results incrementally to simulate real streaming
    let mut accumulated_items = Vec::new();
    let mut accumulated_warnings = Vec::new();

    while pos < bytes.len() {
        let size = chunk_sizes
            .get(chunk_idx % chunk_sizes.len())
            .copied()
            .unwrap_or(1)
            .min(bytes.len() - pos);

        let mut end = pos + size;
        while end < bytes.len() && !input.is_char_boundary(end) {
            end += 1;
        }
        end = end.min(bytes.len());

        if let Ok(chunk) = std::str::from_utf8(&bytes[pos..end]) {
            let yields = parser.parse_and_resolve(chunk, Path::new("."));

            // Collect warnings from this chunk
            accumulated_warnings.extend(parser.collect_warnings(&yields));

            // Convert yields to DisplayItems
            for y in yields {
                if let Some(di) = y.to_display_item(true) {
                    accumulated_items.push(di);
                }
            }
        }
        pos = end;
        chunk_idx += 1;
    }

    // Handle any remainder and get the final diff
    let (diff, mut final_items, final_warnings) = parser.final_resolve(Path::new("."));

    accumulated_items.append(&mut final_items);
    accumulated_warnings.extend(final_warnings);

    ParserResult {
        diff,
        items: accumulated_items,
        warnings: accumulated_warnings,
    }
}

fn run_parser_split_at_char(
    baseline: &HashMap<String, String>,
    input: &str,
    split_char: char,
) -> ParserResult {
    let mut parser = StreamParser::new(baseline);

    if let Some(idx) = input.find(split_char) {
        let split_pos = input
            .char_indices()
            .find(|(i, _)| *i >= idx)
            .map(|(i, _)| i + 1)
            .unwrap_or(input.len());
        let (part1, part2) = input.split_at(split_pos.min(input.len()));
        parser.feed(part1);
        parser.feed(part2);
    } else {
        parser.feed(input);
    }

    let (diff, items, warnings) = parser.final_resolve(Path::new("."));
    ParserResult {
        diff,
        items,
        warnings,
    }
}

// =============================================================================
// PROPTEST STRATEGIES
// =============================================================================

fn line_ending() -> impl Strategy<Value = &'static str> {
    prop_oneof![Just("\n"), Just("\r\n")]
}

fn indent() -> impl Strategy<Value = &'static str> {
    prop_oneof![Just(""), Just("  "), Just("    "), Just("\t")]
}

fn chunk_sizes() -> impl Strategy<Value = Vec<usize>> {
    prop::collection::vec(1usize..100, 5..20)
}

/// Comprehensive grammar-based LLM output generator
fn llm_output() -> impl Strategy<Value = String> {
    let valid_patch = (indent(), line_ending()).prop_map(|(ind, le)| {
        format!(
            "File: {}{le}{ind}<<<<<<< SEARCH{le}{ind}    println!(\"Hello\");{le}{ind}======={le}{ind}    println!(\"World\");{le}{ind}>>>>>>> REPLACE{le}",
            TEST_FILENAME
        )
    });

    let invalid_patch = (indent(), line_ending()).prop_map(|(ind, le)| {
        format!(
            "File: {}{le}{ind}<<<<<<< SEARCH{le}{ind}    nonexistent();{le}{ind}======={le}{ind}    fixed();{le}{ind}>>>>>>> REPLACE{le}",
            TEST_FILENAME
        )
    });

    let file_creation = line_ending().prop_map(|le| {
        format!("File: new.rs{le}<<<<<<< SEARCH{le}======={le}fn new() {{}}{le}>>>>>>> REPLACE{le}")
    });

    let content_deletion = line_ending().prop_map(|le| {
        format!(
            "File: {}{le}<<<<<<< SEARCH{le}    println!(\"Hello\");{le}======={le}>>>>>>> REPLACE{le}",
            TEST_FILENAME
        )
    });

    let broken_markers = prop_oneof![
        Just("<<<<<<<\n".to_string()),
        Just("<<<<<<< SEARC\n".to_string()),
        Just(">>>>>>>REPLACE\n".to_string()),
        Just("=====\n".to_string()),
        Just("File: \n".to_string()),
    ];

    let noise = prop_oneof![
        "[a-zA-Z0-9 .,!?*`_~]{1,80}",
        Just("-  ".to_string()),
        Just("1.  ".to_string()),
        Just("Here are the changes:\n\n".to_string()),
        Just("```rust\nfn example() {}\n```\n".to_string()),
    ];

    prop::collection::vec(
        prop_oneof![
            4 => valid_patch,
            2 => invalid_patch,
            1 => file_creation,
            1 => content_deletion,
            2 => broken_markers,
            3 => noise,
        ],
        1..32,
    )
    .prop_map(|blocks| blocks.join(""))
}

/// Chaos generator for panic testing
fn chaos_stream() -> impl Strategy<Value = String> {
    let chunks = prop_oneof![
        "[\\PC\\s]*",
        Just("<<<<<<< SEARCH\n".to_string()),
        Just("=======\n".to_string()),
        Just(">>>>>>> REPLACE\n".to_string()),
        Just("File: src/main.rs\n".to_string()),
        Just("    <<<<<<< SEARCH\n".to_string()),
        Just("<<<<<<<".to_string()),
        Just("<<<<<<< SEARCH\r\n".to_string()),
        Just("fn main() {}\n".to_string()),
    ];

    prop::collection::vec(chunks, 1..30).prop_map(|v| v.join(""))
}

// =============================================================================
// PROPTEST: PANIC RESISTANCE
// =============================================================================

proptest! {
    #![proptest_config(ProptestConfig::with_cases(500))]

    #[test]
    fn parser_never_panics_on_chaos(s in chaos_stream()) {
        let baseline = HashMap::new();
        let mut parser = StreamParser::new(&baseline);
        parser.feed(&s);
        let _ = parser.final_resolve(Path::new("."));
    }

    #[test]
    fn parser_never_panics_on_random(s in any::<String>()) {
        let baseline = HashMap::new();
        let mut parser = StreamParser::new(&baseline);
        parser.feed(&s);
        let _ = parser.final_resolve(Path::new("."));
    }

    #[test]
    fn parser_never_panics_on_grammar(s in llm_output()) {
        let baseline = create_baseline();
        let mut parser = StreamParser::new(&baseline);
        parser.feed(&s);
        let _ = parser.final_resolve(Path::new("."));
    }
}

// =============================================================================
// PROPTEST: FRAGMENTATION CONSISTENCY
// =============================================================================

proptest! {
    #![proptest_config(ProptestConfig::with_cases(300))]

    #[test]
    fn fragmentation_produces_identical_output(input in llm_output()) {
        let baseline = create_baseline();

        let whole = run_parser_whole(&baseline, &input);
        let char_by_char = run_parser_char_by_char(&baseline, &input);
        let split_lt = run_parser_split_at_char(&baseline, &input, '<');
        let split_eq = run_parser_split_at_char(&baseline, &input, '=');
        let split_nl = run_parser_split_at_char(&baseline, &input, '\n');

        // Diff consistency
        assert_eq!(whole.diff, char_by_char.diff, "char-by-char diff mismatch");
        assert_eq!(whole.diff, split_lt.diff, "split-at-< diff mismatch");
        assert_eq!(whole.diff, split_eq.diff, "split-at-= diff mismatch");
        assert_eq!(whole.diff, split_nl.diff, "split-at-newline diff mismatch");

        // Structure consistency
        assert_eq!(whole.items, char_by_char.items, "char-by-char items mismatch");

        // Warning consistency
        assert_eq!(whole.warnings, char_by_char.warnings, "char-by-char warnings mismatch");
    }

    #[test]
    fn random_chunk_sizes_produce_identical_output(
        input in llm_output(),
        sizes in chunk_sizes()
    ) {
        let baseline = create_baseline();

        let whole = run_parser_whole(&baseline, &input);
        let chunked = run_parser_random_chunks(&baseline, &input, &sizes);

        assert_eq!(whole.diff, chunked.diff, "random chunk diff mismatch");
    }

    #[test]
    fn valid_patch_produces_diff(ind in indent(), le in line_ending()) {
        let baseline = create_baseline();

        let patch = format!(
            "File: {}{le}{ind}<<<<<<< SEARCH{le}{ind}    println!(\"Hello\");{le}{ind}======={le}{ind}    println!(\"World\");{le}{ind}>>>>>>> REPLACE{le}",
            TEST_FILENAME
        );

        let result = run_parser_whole(&baseline, &patch);

        assert!(!result.diff.is_empty(), "valid patch must produce diff");
        assert!(result.warnings.is_empty(), "valid patch must not warn");

        let has_diff_block = result.items.iter().any(|i| matches!(i, DisplayItem::Diff(_)));
        assert!(has_diff_block, "valid patch must produce DiffBlock");
    }
}

// =============================================================================
// EXPLICIT EDGE CASE TESTS
// =============================================================================

#[test]
fn test_marker_content_inside_search_block() {
    let baseline: HashMap<String, String> = [(
        "docs.md".to_string(),
        "The marker <<<<<<< SEARCH appears in docs\n".to_string(),
    )]
    .into_iter()
    .collect();

    let input = "File: docs.md\n<<<<<<< SEARCH\nThe marker <<<<<<< SEARCH appears in docs\n=======\nFixed\n>>>>>>> REPLACE\n";

    let result = run_parser_whole(&baseline, input);
    assert!(!result.diff.is_empty(), "should handle marker-like content");
}

#[test]
fn test_empty_search_creates_file() {
    let baseline = HashMap::new();
    let input = "File: new.rs\n<<<<<<< SEARCH\n=======\nfn new() {}\n>>>>>>> REPLACE\n";

    let result = run_parser_whole(&baseline, input);

    assert!(!result.diff.is_empty());
    assert!(result.diff.contains("+fn new() {}"));
}

#[test]
fn test_empty_replace_deletes_content() {
    let baseline = create_baseline();
    let input = format!(
        "File: {}\n<<<<<<< SEARCH\n    println!(\"Hello\");\n=======\n>>>>>>> REPLACE\n",
        TEST_FILENAME
    );

    let result = run_parser_whole(&baseline, &input);

    assert!(!result.diff.is_empty());
    assert!(result.diff.contains("-    println!(\"Hello\");"));
}

#[test]
fn test_indentation_mismatch_rejected() {
    let baseline = create_baseline();

    // SEARCH has 4 spaces, separator has 2 - should not match as patch
    let input = "File: src/main.rs\n    <<<<<<< SEARCH\n    println!(\"Hello\");\n  =======\n    println!(\"World\");\n    >>>>>>> REPLACE\n";

    let result = run_parser_whole(&baseline, input);

    let has_diff = result
        .items
        .iter()
        .any(|i| matches!(i, DisplayItem::Diff(_)));
    assert!(!has_diff, "mismatched indent should not produce DiffBlock");
}

#[test]
fn test_consecutive_file_headers() {
    let baseline = HashMap::new();
    let input =
        "File: foo.rs\nFile: bar.rs\n<<<<<<< SEARCH\n=======\nfn bar() {}\n>>>>>>> REPLACE\n";

    let result = run_parser_whole(&baseline, input);
    assert!(result.diff.contains("bar.rs"));
}

#[test]
fn test_file_header_decorators() {
    let baseline = create_baseline();

    let decorated = "File: **src/main.rs**\n<<<<<<< SEARCH\n    println!(\"Hello\");\n=======\n    println!(\"World\");\n>>>>>>> REPLACE\n";
    let result = run_parser_whole(&baseline, decorated);
    assert!(!result.diff.is_empty(), "should strip ** decorators");

    let backtick = "File: `src/main.rs`\n<<<<<<< SEARCH\n    println!(\"Hello\");\n=======\n    println!(\"World\");\n>>>>>>> REPLACE\n";
    let result = run_parser_whole(&baseline, backtick);
    assert!(!result.diff.is_empty(), "should strip backtick decorators");
}

#[test]
fn test_multiple_patches_same_file() {
    let baseline: HashMap<String, String> =
        [("multi.rs".to_string(), "line1\nline2\nline3\n".to_string())]
            .into_iter()
            .collect();

    let input = "File: multi.rs\n<<<<<<< SEARCH\nline1\n=======\nmod1\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nline2\n=======\nmod2\n>>>>>>> REPLACE\n";

    let result = run_parser_whole(&baseline, input);

    assert!(result.diff.contains("-line1"));
    assert!(result.diff.contains("+mod1"));
    assert!(result.diff.contains("-line2"));
    assert!(result.diff.contains("+mod2"));
}

#[test]
fn test_file_not_in_context_but_on_disk() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    let file_path = root.join("on_disk.rs");
    std::fs::write(&file_path, "original\n").unwrap();

    let baseline = HashMap::new();
    let input = "File: on_disk.rs\n<<<<<<< SEARCH\noriginal\n=======\nmodified\n>>>>>>> REPLACE\n";

    let mut parser = StreamParser::new(&baseline);
    parser.feed(input);
    let (diff, _, warnings) = parser.final_resolve(root);

    assert!(
        !warnings.is_empty(),
        "should warn about file not in context"
    );
    assert!(
        warnings
            .iter()
            .any(|w| w.contains("not in the session context"))
    );
    assert!(!diff.is_empty(), "should still produce diff");
}

#[test]
fn test_dangling_marker_at_eof() {
    let baseline = HashMap::new();
    let input = "Some text\n<<<<<";

    let result = run_parser_whole(&baseline, input);

    let has_content = result.items.iter().any(|item| match item {
        DisplayItem::Markdown(t) => t.contains("<<<<<") || t.contains("Some text"),
        _ => false,
    });
    assert!(has_content, "dangling marker should become text");
}

#[test]
fn test_unicode_fragmentation() {
    let baseline: HashMap<String, String> = [("emoji.txt".to_string(), "Old: 😐\n".to_string())]
        .into_iter()
        .collect();

    let input = "File: emoji.txt\n<<<<<<< SEARCH\nOld: 😐\n=======\nNew: 🦀\n>>>>>>> REPLACE\n";

    let whole = run_parser_whole(&baseline, input);
    let fragmented = run_parser_char_by_char(&baseline, input);

    assert!(!whole.diff.is_empty());
    assert!(whole.diff.contains("🦀"));
    assert_eq!(
        whole.diff, fragmented.diff,
        "unicode fragmentation mismatch"
    );
}

#[test]
fn test_very_long_lines() {
    let long_line = "x".repeat(10_000);
    let baseline: HashMap<String, String> = [("long.txt".to_string(), format!("{}\n", long_line))]
        .into_iter()
        .collect();

    let input = format!(
        "File: long.txt\n<<<<<<< SEARCH\n{}\n=======\n{}\n>>>>>>> REPLACE\n",
        long_line,
        "y".repeat(10_000)
    );

    let result = run_parser_whole(&baseline, &input);
    assert!(!result.diff.is_empty(), "should handle very long lines");
}

#[test]
fn test_deep_indentation() {
    let deep_indent = "        ".repeat(10); // 80 spaces
    let baseline: HashMap<String, String> =
        [("deep.py".to_string(), format!("{}code()\n", deep_indent))]
            .into_iter()
            .collect();

    let input = format!(
        "File: deep.py\n<<<<<<< SEARCH\n{}code()\n=======\n{}modified()\n>>>>>>> REPLACE\n",
        deep_indent, deep_indent
    );

    let result = run_parser_whole(&baseline, &input);
    assert!(!result.diff.is_empty(), "should handle deep indentation");
}

// =============================================================================
// DETERMINISTIC STRESS SUITE
// =============================================================================

#[test]
fn test_stress_consistency_suite() {
    let cases = vec![
        (
            "Standard Replacement",
            vec![("main.rs", "fn main() {\n    println!(\"Old\");\n}\n")],
            "File: main.rs\n<<<<<<< SEARCH\n    println!(\"Old\");\n=======\n    println!(\"New\");\n>>>>>>> REPLACE\n",
        ),
        (
            "File Creation",
            vec![],
            "File: new.py\n<<<<<<< SEARCH\n=======\nprint('hello')\n>>>>>>> REPLACE\n",
        ),
        (
            "Python Indentation Patch",
            vec![(
                "utils.py",
                "def check(x):\n    if x:\n        return True\n    return False\n",
            )],
            "File: utils.py\n<<<<<<< SEARCH\n    if x:\n        return True\n=======\n    if x:\n        # Logging added\n        print(x)\n        return True\n>>>>>>> REPLACE\n",
        ),
        (
            "Adjacent Patches",
            vec![("cfg.txt", "A=1\nB=1\n")],
            "File: cfg.txt\n<<<<<<< SEARCH\nA=1\n=======\nA=2\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nB=1\n=======\nB=2\n>>>>>>> REPLACE\n",
        ),
        (
            "With Noise",
            vec![("readme.md", "# Title\nBody")],
            "Updating readme.\n\nFile: readme.md\n<<<<<<< SEARCH\nBody\n=======\nNew Body\n>>>>>>> REPLACE\n\nDone.",
        ),
        (
            "Unicode",
            vec![("emoji.txt", "Old: 😐")],
            "File: emoji.txt\n<<<<<<< SEARCH\nOld: 😐\n=======\nNew: 😎\n>>>>>>> REPLACE\n",
        ),
        (
            "CRLF",
            vec![("win.txt", "line1\r\nline2\r\n")],
            "File: win.txt\r\n<<<<<<< SEARCH\r\nline1\r\n=======\r\nmodified\r\n>>>>>>> REPLACE\r\n",
        ),
        (
            "Panic Case (Trailing Space)",
            vec![("src/main.rs", "fn main() {\n    println!(\"Hello\");\n}\n")],
            "File: src/main.rs\n<<<<<<< SEARCH\n    println!(\"Hello\");\n=======\n    println!(\"World\");\n>>>>>>> REPLACE\n ",
        ),
    ];

    for (name, files, input) in cases {
        let mut baseline = HashMap::new();
        for (path, content) in files {
            baseline.insert(path.to_string(), content.to_string());
        }

        let whole = run_parser_whole(&baseline, input);
        let fragmented = run_parser_char_by_char(&baseline, input);

        assert_eq!(
            whole.diff, fragmented.diff,
            "Case '{}': diff mismatch",
            name
        );
        assert_eq!(
            whole.items, fragmented.items,
            "Case '{}': items mismatch",
            name
        );
    }
}
