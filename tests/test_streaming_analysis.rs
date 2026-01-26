use aico::diffing::parser::StreamParser;
use aico::models::DisplayItem;
use std::collections::HashMap;
use std::path::Path;

#[test]
fn test_analyze_streaming_partial_output() {
    let root = Path::new(".");
    let mut contents = HashMap::new();
    contents.insert("app.py".to_string(), "print('hello')\n".to_string());
    let mut parser = StreamParser::new(&contents);

    // Part 1: Just conversational text
    let res1 = "I will update the file.\n\n";
    let items1: Vec<DisplayItem> = parser
        .parse_and_resolve(res1, root)
        .into_iter()
        .filter_map(|i| i.to_display_item(false))
        .collect();
    assert_eq!(items1.len(), 1);
    assert!(matches!(items1[0], DisplayItem::Markdown(_)));

    // Part 2: File header added
    let res2 = "File: app.py\n";
    let items2: Vec<DisplayItem> = parser
        .parse_and_resolve(res2, root)
        .into_iter()
        .filter_map(|i| i.to_display_item(false))
        .collect();
    assert_eq!(items2.len(), 1);
    if let DisplayItem::Markdown(ref m) = items2[0] {
        assert!(m.contains("File: `app.py`"));
    }

    // Part 3: Incomplete block starts
    let res3 = "<<<<<<< SEARCH\nprint('hello')\n";
    let items3: Vec<DisplayItem> = parser
        .parse_and_resolve(res3, root)
        .into_iter()
        .filter_map(|i| i.to_display_item(false))
        .collect();
    assert_eq!(items3.len(), 0);

    // Part 4: Block completes
    let res4 = "=======\nprint('world')\n>>>>>>> REPLACE\n";
    let processed4 = parser.parse_and_resolve(res4, root);
    let items4: Vec<DisplayItem> = processed4
        .into_iter()
        .filter_map(|y| y.to_display_item(false))
        .collect();

    assert_eq!(items4.len(), 2);
    assert!(matches!(items4[0], DisplayItem::Diff(_)));

    // Verify the second item is just the newline
    match &items4[1] {
        DisplayItem::Markdown(s) => assert_eq!(s, "\n"),
        _ => panic!("Expected trailing newline as Markdown"),
    }
}

#[test]
fn test_analyze_streaming_with_nested_markers_in_code() {
    let root = std::path::Path::new(".");
    let mut contents = HashMap::new();
    contents.insert("tests.rs".to_string(), "original".to_string());
    let mut parser = StreamParser::new(&contents);

    let response = "File: tests.rs\n<<<<<<< SEARCH\noriginal\n=======\nlet nested = \"File: inner.py\n<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE\";\n>>>>>>> REPLACE";

    let (_, yields, _) = parser.finish(response);
    let mut items = Vec::new();
    let processed = parser.process_yields(yields, root);
    for y in processed {
        if let Some(di) = y.to_display_item(true) {
            items.push(di);
        }
    }

    let diff_count = items
        .iter()
        .filter(|i| matches!(i, DisplayItem::Diff(_)))
        .count();
    assert_eq!(diff_count, 1);

    if let DisplayItem::Diff(d) = &items[1] {
        assert!(d.contains("let nested = \"File: inner.py"));
        assert!(d.contains(">>>>>>> REPLACE\";"));
    }
}

#[test]
fn test_is_incomplete_ignores_conversational_mentions() {
    let contents = HashMap::new();
    let mut parser = StreamParser::new(&contents);

    let response = "I will use the <<<<<<< SEARCH block syntax to help you.";
    let (_, yields, _) = parser.finish(response);
    let items: Vec<DisplayItem> = yields
        .into_iter()
        .filter_map(|i| i.to_display_item(true))
        .collect();

    assert_eq!(items.len(), 1);
    match &items[0] {
        DisplayItem::Markdown(t) => assert_eq!(t, response),
        _ => panic!("Should have been identified as Markdown"),
    }
}

#[test]
fn test_feed_complete_adds_newline_correctly() {
    let contents = HashMap::new();
    let mut parser = StreamParser::new(&contents);

    // Case 1: No trailing newline -> Adds one
    parser.feed_complete("foo");
    assert_eq!(parser.get_pending_content(), "foo\n");

    // Reset
    let mut parser2 = StreamParser::new(&contents);

    // Case 2: Has trailing newline -> Does not add extra
    parser2.feed_complete("bar\n");
    assert_eq!(parser2.get_pending_content(), "bar\n");
}

#[test]
fn test_partial_marker_not_leaked_as_markdown() {
    use aico::models::StreamYieldItem;

    let root = std::path::Path::new(".");
    let mut contents = HashMap::new();
    contents.insert("src/main.rs".to_string(), "fn main() {}\n".to_string());
    let mut parser = StreamParser::new(&contents);

    // Chunk 1: File header with 2-char partial marker
    let chunk1 = "File: src/main.rs\n<<";
    let yields1 = parser.parse_and_resolve(chunk1, root);

    // Should yield FileHeader, but << should remain in buffer
    assert_eq!(yields1.len(), 1);
    assert!(matches!(yields1[0], StreamYieldItem::FileHeader(_)));

    let pending = parser.get_pending_content();
    assert_eq!(pending, "<<");
    assert!(
        !parser.is_pending_displayable(),
        "2-char prefix should not be displayable"
    );

    // Chunk 2: Complete the marker
    let chunk2 = "<<<<< SEARCH\nfn main() {}\n=======\nfn new() {}\n>>>>>>> REPLACE\n";
    let yields2 = parser.parse_and_resolve(chunk2, root);

    assert!(
        yields2
            .iter()
            .any(|i| matches!(i, StreamYieldItem::DiffBlock(_)))
    );
}

#[test]
fn test_partial_file_header_not_leaked() {
    use aico::models::StreamYieldItem;

    let root = std::path::Path::new(".");
    let contents = HashMap::new();
    let mut parser = StreamParser::new(&contents);

    let chunk1 = "File";
    let yields1 = parser.parse_and_resolve(chunk1, root);

    assert_eq!(yields1.len(), 0);
    assert_eq!(parser.get_pending_content(), "File");
    assert!(
        !parser.is_pending_displayable(),
        "'File' prefix should not be displayable"
    );

    let chunk2 = ": new.rs\n<<<<<<< SEARCH\n=======\nfn new() {}\n>>>>>>> REPLACE\n";
    let yields2 = parser.parse_and_resolve(chunk2, root);

    assert!(
        yields2
            .iter()
            .any(|i| matches!(i, StreamYieldItem::FileHeader(_)))
    );
}

#[test]
fn test_three_char_partial_marker_held_back() {
    let root = std::path::Path::new(".");
    let mut contents = HashMap::new();
    contents.insert("test.py".to_string(), "old\n".to_string());
    let mut parser = StreamParser::new(&contents);

    parser.parse_and_resolve("File: test.py\n", root);

    let chunk = "<<<";
    let yields = parser.parse_and_resolve(chunk, root);

    assert_eq!(yields.len(), 0);
    assert_eq!(parser.get_pending_content(), "<<<");
    assert!(
        !parser.is_pending_displayable(),
        "3-char prefix should not be displayable"
    );
}

#[test]
fn test_exact_debug_log_sequence() {
    use aico::models::StreamYieldItem;

    let root = std::path::Path::new(".");
    let mut contents = HashMap::new();
    contents.insert(
        "src/diffing/parser.rs".to_string(),
        "use crate::diffing::diff_utils;\n".to_string(),
    );
    let mut parser = StreamParser::new(&contents);

    let chunks = vec![
        "File",
        ": src",
        "/diff",
        "ing",
        "/parser",
        ".rs\n<<",
        "<<<<< SEARCH\nuse",
        " c",
        "rate::diffing::diff",
        "_utils",
        ";\n=======\nuse crate::diffing::diff_utils;\nuse std::fs;\n>>>>>>> REPLACE\n",
    ];

    let mut all_items = Vec::new();
    let mut leaked_partial_markers = Vec::new();

    for chunk in chunks {
        let yields = parser.parse_and_resolve(chunk, root);

        if !parser.get_pending_content().is_empty() && parser.is_pending_displayable() {
            leaked_partial_markers.push(parser.get_pending_content());
        }

        all_items.extend(yields);
    }

    let has_file_header = all_items
        .iter()
        .any(|i| matches!(i, StreamYieldItem::FileHeader(_)));
    let has_diff = all_items
        .iter()
        .any(|i| matches!(i, StreamYieldItem::DiffBlock(_)));

    assert!(has_file_header, "Should have file header");
    assert!(has_diff, "Should have diff block");
    assert!(
        leaked_partial_markers.is_empty(),
        "Leaked markers: {:?}",
        leaked_partial_markers
    );
}

#[test]
fn test_single_char_partials_held_back() {
    let root = std::path::Path::new(".");
    let contents = HashMap::new();
    let mut parser = StreamParser::new(&contents);

    let chunk1 = "<";
    let yields1 = parser.parse_and_resolve(chunk1, root);
    assert_eq!(yields1.len(), 0, "Single '<' should be held in buffer");
    assert_eq!(parser.get_pending_content(), "<");
    assert!(
        !parser.is_pending_displayable(),
        "'<' should not be displayable"
    );

    let mut parser2 = StreamParser::new(&contents);
    let chunk2 = "Fi";
    let yields2 = parser2.parse_and_resolve(chunk2, root);
    assert_eq!(yields2.len(), 0, "'Fi' should be held in buffer");
    assert_eq!(parser2.get_pending_content(), "Fi");
    assert!(
        !parser2.is_pending_displayable(),
        "'Fi' should not be displayable"
    );
}
