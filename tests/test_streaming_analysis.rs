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
    assert_eq!(items4.len(), 1);
    assert!(matches!(items4[0], DisplayItem::Diff(_)));
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
