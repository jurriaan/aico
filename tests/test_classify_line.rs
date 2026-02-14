use aico::ui::markdown_streamer::{BlockKind, ClassifiedLine, MarkdownStreamer};

fn make_streamer() -> MarkdownStreamer {
    MarkdownStreamer::new()
}

fn make_streamer_with_fence() -> MarkdownStreamer {
    let mut s = MarkdownStreamer::new();
    s.print_chunk(&mut Vec::new(), "```rust\n").unwrap();
    s
}

fn make_streamer_with_math() -> MarkdownStreamer {
    let mut s = MarkdownStreamer::new();
    s.print_chunk(&mut Vec::new(), "$$\n").unwrap();
    s
}

fn make_streamer_with_table() -> MarkdownStreamer {
    let mut s = MarkdownStreamer::new();
    s.print_chunk(&mut Vec::new(), "| A | B |\n").unwrap();
    s
}

#[test]
fn classify_paragraph() {
    let s = make_streamer();
    let result = s.classify_line("Hello world");
    assert_eq!(result.blockquote_depth, 0);
    assert_eq!(result.kind, BlockKind::Paragraph);
}

#[test]
fn classify_blank_line() {
    let s = make_streamer();
    assert_eq!(s.classify_line("").kind, BlockKind::BlankLine);
    assert_eq!(s.classify_line("   ").kind, BlockKind::BlankLine);
}

#[test]
fn classify_header_levels() {
    let s = make_streamer();

    // GIVEN various ATX header levels
    // WHEN classified
    // THEN each returns the correct level and stripped text
    let h1 = s.classify_line("# Title");
    assert_eq!(
        h1,
        ClassifiedLine {
            blockquote_depth: 0,
            content: "# Title".to_string(),
            kind: BlockKind::Header {
                level: 1,
                text: "Title".to_string(),
            },
        }
    );

    let h2 = s.classify_line("## Subtitle");
    assert_eq!(
        h2.kind,
        BlockKind::Header {
            level: 2,
            text: "Subtitle".to_string(),
        }
    );

    let h6 = s.classify_line("###### Deep");
    assert_eq!(
        h6.kind,
        BlockKind::Header {
            level: 6,
            text: "Deep".to_string(),
        }
    );
}

#[test]
fn classify_header_with_trailing_hashes() {
    let s = make_streamer();
    let result = s.classify_line("## Title ##");
    assert_eq!(
        result.kind,
        BlockKind::Header {
            level: 2,
            text: "Title".to_string(),
        }
    );
}

#[test]
fn classify_thematic_break() {
    let s = make_streamer();
    assert_eq!(s.classify_line("---").kind, BlockKind::ThematicBreak);
    assert_eq!(s.classify_line("***").kind, BlockKind::ThematicBreak);
    assert_eq!(s.classify_line("___").kind, BlockKind::ThematicBreak);
    assert_eq!(s.classify_line("- - -").kind, BlockKind::ThematicBreak);
    assert_eq!(s.classify_line("* * *").kind, BlockKind::ThematicBreak);
}

#[test]
fn classify_thematic_break_over_list() {
    // GIVEN `* * *` which could be a list item or a thematic break
    // WHEN classified
    // THEN thematic break takes precedence (CommonMark spec §4.1)
    let s = make_streamer();
    let result = s.classify_line("* * *");
    assert_eq!(result.kind, BlockKind::ThematicBreak);
}

#[test]
fn classify_unordered_list() {
    let s = make_streamer();

    let result = s.classify_line("- Item");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "-".to_string(),
            separator: " ".to_string(),
            content: "Item".to_string(),
            is_ordered: false,
        }
    );

    let result2 = s.classify_line("* Bullet");
    assert_eq!(
        result2.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "*".to_string(),
            separator: " ".to_string(),
            content: "Bullet".to_string(),
            is_ordered: false,
        }
    );
}

#[test]
fn classify_ordered_list() {
    let s = make_streamer();
    let result = s.classify_line("1. First");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "1.".to_string(),
            separator: " ".to_string(),
            content: "First".to_string(),
            is_ordered: true,
        }
    );
}

#[test]
fn classify_indented_list() {
    let s = make_streamer();
    let result = s.classify_line("   - Nested");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 3,
            marker: "-".to_string(),
            separator: " ".to_string(),
            content: "Nested".to_string(),
            is_ordered: false,
        }
    );
}

#[test]
fn classify_list_with_wide_separator() {
    let s = make_streamer();
    let result = s.classify_line("1.  Header");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "1.".to_string(),
            separator: "  ".to_string(),
            content: "Header".to_string(),
            is_ordered: true,
        }
    );
}

#[test]
fn classify_fence_open_backtick() {
    let s = make_streamer();
    let result = s.classify_line("```rust");
    assert_eq!(
        result.kind,
        BlockKind::FenceOpen {
            fence_char: '`',
            fence_len: 3,
            indent: 0,
            lang: "rust".to_string(),
        }
    );
}

#[test]
fn classify_fence_open_tilde() {
    let s = make_streamer();
    let result = s.classify_line("~~~python");
    assert_eq!(
        result.kind,
        BlockKind::FenceOpen {
            fence_char: '~',
            fence_len: 3,
            indent: 0,
            lang: "python".to_string(),
        }
    );
}

#[test]
fn classify_fence_open_indented() {
    let s = make_streamer();
    let result = s.classify_line("  ```bash");
    assert_eq!(
        result.kind,
        BlockKind::FenceOpen {
            fence_char: '`',
            fence_len: 3,
            indent: 2,
            lang: "bash".to_string(),
        }
    );
}

#[test]
fn classify_fence_open_no_lang() {
    let s = make_streamer();
    let result = s.classify_line("```");
    assert_eq!(
        result.kind,
        BlockKind::FenceOpen {
            fence_char: '`',
            fence_len: 3,
            indent: 0,
            lang: "bash".to_string(),
        }
    );
}

#[test]
fn classify_fence_open_backtick_in_info_rejected() {
    // GIVEN a backtick fence with backtick in info string
    // WHEN classified
    // THEN it is NOT a fence open (CommonMark spec §4.5)
    let s = make_streamer();
    let result = s.classify_line("```info`string");
    assert_eq!(result.kind, BlockKind::Paragraph);
}

#[test]
fn classify_fence_content() {
    // GIVEN an active fence
    // WHEN a non-closing line is classified
    // THEN it is FenceContent
    let s = make_streamer_with_fence();
    let result = s.classify_line("let x = 42;");
    assert_eq!(result.kind, BlockKind::FenceContent);
}

#[test]
fn classify_fence_close() {
    // GIVEN an active backtick fence of length 3
    // WHEN a matching closing fence is classified
    // THEN it is FenceClose
    let s = make_streamer_with_fence();
    let result = s.classify_line("```");
    assert_eq!(result.kind, BlockKind::FenceClose);
}

#[test]
fn classify_fence_close_longer() {
    // Closing fence may be longer than opening
    let s = make_streamer_with_fence();
    let result = s.classify_line("````");
    assert_eq!(result.kind, BlockKind::FenceClose);
}

#[test]
fn classify_fence_close_too_short() {
    // Closing fence shorter than opening is treated as content
    let s = make_streamer_with_fence();
    let result = s.classify_line("``");
    assert_eq!(result.kind, BlockKind::FenceContent);
}

#[test]
fn classify_fence_close_wrong_char() {
    // Tilde fence doesn't close backtick fence
    let s = make_streamer_with_fence();
    let result = s.classify_line("~~~");
    assert_eq!(result.kind, BlockKind::FenceContent);
}

#[test]
fn classify_fence_close_with_info_rejected() {
    // Closing fence with info string text is content, not a close
    let s = make_streamer_with_fence();
    let result = s.classify_line("``` something");
    assert_eq!(result.kind, BlockKind::FenceContent);
}

#[test]
fn classify_math_open() {
    let s = make_streamer();
    let result = s.classify_line("$$");
    assert_eq!(result.kind, BlockKind::MathOpen);
}

#[test]
fn classify_math_content() {
    let s = make_streamer_with_math();
    let result = s.classify_line("x^2 + y^2 = z^2");
    assert_eq!(result.kind, BlockKind::MathContent);
}

#[test]
fn classify_math_close() {
    let s = make_streamer_with_math();
    let result = s.classify_line("$$");
    assert_eq!(result.kind, BlockKind::MathClose);
}

#[test]
fn classify_table_row() {
    let s = make_streamer();
    let result = s.classify_line("| A | B |");
    assert_eq!(result.kind, BlockKind::TableRow);
}

#[test]
fn classify_table_separator_when_in_table() {
    let s = make_streamer_with_table();
    let result = s.classify_line("|---|---|");
    assert_eq!(result.kind, BlockKind::TableSeparator);
}

#[test]
fn classify_table_separator_not_in_table() {
    // GIVEN not in a table
    // WHEN a separator-like line appears
    // THEN it is NOT classified as TableSeparator
    let s = make_streamer();
    let result = s.classify_line("|---|---|");
    // Without being in a table, this matches TableRow (since RE_TABLE_ROW matches it)
    // or could be something else; the key point is it's NOT TableSeparator
    assert_ne!(result.kind, BlockKind::TableSeparator);
}

#[test]
fn classify_blockquote_with_header() {
    // GIVEN a blockquoted header
    // WHEN classified
    // THEN blockquote_depth is counted and inner content is a Header
    let s = make_streamer();
    let result = s.classify_line("> ## Title");
    assert_eq!(result.blockquote_depth, 1);
    assert_eq!(result.content, "## Title");
    assert_eq!(
        result.kind,
        BlockKind::Header {
            level: 2,
            text: "Title".to_string(),
        }
    );
}

#[test]
fn classify_nested_blockquote() {
    let s = make_streamer();
    let result = s.classify_line("> > Deep content");
    assert_eq!(result.blockquote_depth, 2);
    assert_eq!(result.kind, BlockKind::Paragraph);
}

#[test]
fn classify_blockquote_with_list() {
    let s = make_streamer();
    let result = s.classify_line("> - Item");
    assert_eq!(result.blockquote_depth, 1);
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "-".to_string(),
            separator: " ".to_string(),
            content: "Item".to_string(),
            is_ordered: false,
        }
    );
}

#[test]
fn classify_blockquote_with_thematic_break() {
    let s = make_streamer();
    let result = s.classify_line("> ---");
    assert_eq!(result.blockquote_depth, 1);
    assert_eq!(result.kind, BlockKind::ThematicBreak);
}

#[test]
fn classify_blockquote_blank() {
    let s = make_streamer();
    let result = s.classify_line("> ");
    assert_eq!(result.blockquote_depth, 1);
    assert_eq!(result.kind, BlockKind::BlankLine);
}

#[test]
fn classify_fence_ignores_blockquotes() {
    // GIVEN an active fence
    // WHEN a line looks like a blockquoted fence close
    // THEN it is still FenceContent (fences don't strip blockquotes)
    let s = make_streamer_with_fence();
    let result = s.classify_line("> ```");
    assert_eq!(result.blockquote_depth, 0);
    assert_eq!(result.kind, BlockKind::FenceContent);
}

#[test]
fn classify_empty_list_item() {
    let s = make_streamer();
    let result = s.classify_line("1. ");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "1.".to_string(),
            separator: " ".to_string(),
            content: "".to_string(),
            is_ordered: true,
        }
    );
}

#[test]
fn classify_longer_fence() {
    let s = make_streamer();
    let result = s.classify_line("````markdown");
    assert_eq!(
        result.kind,
        BlockKind::FenceOpen {
            fence_char: '`',
            fence_len: 4,
            indent: 0,
            lang: "markdown".to_string(),
        }
    );
}

// --- §4.1 Thematic Break Edge Cases ---

#[test]
fn classify_thematic_break_with_indent_1() {
    // Up to 3 spaces of indentation allowed (CommonMark §4.1)
    let s = make_streamer();
    assert_eq!(s.classify_line(" ***").kind, BlockKind::ThematicBreak);
}

#[test]
fn classify_thematic_break_with_indent_2() {
    let s = make_streamer();
    assert_eq!(s.classify_line("  ***").kind, BlockKind::ThematicBreak);
}

#[test]
fn classify_thematic_break_with_indent_3() {
    let s = make_streamer();
    assert_eq!(s.classify_line("   ***").kind, BlockKind::ThematicBreak);
}

#[test]
fn classify_thematic_break_many_chars() {
    // More than 3 characters is still a thematic break
    let s = make_streamer();
    assert_eq!(
        s.classify_line("_____________________________________")
            .kind,
        BlockKind::ThematicBreak
    );
}

#[test]
fn classify_thematic_break_trailing_spaces() {
    let s = make_streamer();
    assert_eq!(
        s.classify_line("- - - -    ").kind,
        BlockKind::ThematicBreak
    );
}

#[test]
fn classify_thematic_break_with_extra_text_rejected() {
    // Characters with extra text: NOT a thematic break (CommonMark §4.1)
    let s = make_streamer();
    assert_ne!(s.classify_line("_ _ _ _ a").kind, BlockKind::ThematicBreak);
}

#[test]
fn classify_thematic_break_mixed_chars_rejected() {
    // Mixed characters: `*-*` is NOT a thematic break
    let s = make_streamer();
    assert_ne!(s.classify_line("*-*").kind, BlockKind::ThematicBreak);
}

// --- §4.2 ATX Heading Edge Cases ---

#[test]
fn classify_header_7_hashes_not_heading() {
    // 7+ `#` is NOT a heading (CommonMark §4.2)
    let s = make_streamer();
    let result = s.classify_line("####### foo");
    assert_eq!(result.kind, BlockKind::Paragraph);
}

#[test]
fn classify_header_no_space_not_heading() {
    // `#` without space is NOT a heading (CommonMark §4.2)
    let s = make_streamer();
    let result = s.classify_line("#5 bolt");
    assert_eq!(result.kind, BlockKind::Paragraph);
}

#[test]
fn classify_header_hashtag_not_heading() {
    let s = make_streamer();
    let result = s.classify_line("#hashtag");
    assert_eq!(result.kind, BlockKind::Paragraph);
}

#[test]
fn classify_header_empty_h2() {
    // Empty headings: `##` with trailing hashes stripped yields empty text
    let s = make_streamer();
    let result = s.classify_line("## ");
    assert_eq!(
        result.kind,
        BlockKind::Header {
            level: 2,
            text: "".to_string(),
        }
    );
}

#[test]
fn classify_header_empty_closing_hashes() {
    // `### ###` → empty heading
    let s = make_streamer();
    let result = s.classify_line("### ###");
    assert_eq!(
        result.kind,
        BlockKind::Header {
            level: 3,
            text: "".to_string(),
        }
    );
}

#[test]
fn classify_header_closing_hash_no_space() {
    // Closing `#` must be preceded by space: `# foo#` → heading text is `foo#`
    let s = make_streamer();
    let result = s.classify_line("# foo#");
    assert_eq!(
        result.kind,
        BlockKind::Header {
            level: 1,
            text: "foo#".to_string(),
        }
    );
}

// --- §6.7 Hard Line Breaks ---

#[test]
fn classify_hard_line_break_trailing_spaces() {
    // Two trailing spaces → should still be a paragraph (block classification doesn't change)
    // but the inline rendering must handle it. At the classify level, it's a Paragraph.
    let s = make_streamer();
    let result = s.classify_line("foo  ");
    assert_eq!(result.kind, BlockKind::Paragraph);
}

#[test]
fn classify_hard_line_break_trailing_backslash() {
    // Trailing backslash → still a paragraph at block level
    let s = make_streamer();
    let result = s.classify_line("foo\\");
    assert_eq!(result.kind, BlockKind::Paragraph);
}

// --- §5.2 List Item Edge Cases ---

#[test]
fn classify_list_plus_marker() {
    // `+` is a valid unordered list marker
    let s = make_streamer();
    let result = s.classify_line("+ Item");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "+".to_string(),
            separator: " ".to_string(),
            content: "Item".to_string(),
            is_ordered: false,
        }
    );
}

#[test]
fn classify_ordered_list_start_gt_1() {
    // Start number > 1 for ordered lists
    let s = make_streamer();
    let result = s.classify_line("3. Third");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "3.".to_string(),
            separator: " ".to_string(),
            content: "Third".to_string(),
            is_ordered: true,
        }
    );
}

#[test]
fn classify_list_empty_marker_only() {
    // Empty list item: `*` alone on a line
    let s = make_streamer();
    // `* ` with nothing after — the regex should match with empty content
    // but `*` alone without space could be tricky
    let result = s.classify_line("* ");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "*".to_string(),
            separator: " ".to_string(),
            content: "".to_string(),
            is_ordered: false,
        }
    );
}

// --- §5.2 Ordered List `)` Delimiter ---

#[test]
fn classify_ordered_list_paren_delimiter() {
    // `1) item` — ordered list with `)` delimiter (common LLM output)
    let s = make_streamer();
    let result = s.classify_line("1) First");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "1)".to_string(),
            separator: " ".to_string(),
            content: "First".to_string(),
            is_ordered: true,
        }
    );
}

#[test]
fn classify_ordered_list_paren_multidigit() {
    let s = make_streamer();
    let result = s.classify_line("12) Twelfth");
    assert_eq!(
        result.kind,
        BlockKind::ListItem {
            indent: 0,
            marker: "12)".to_string(),
            separator: " ".to_string(),
            content: "Twelfth".to_string(),
            is_ordered: true,
        }
    );
}

// --- §2.2 Tab Expansion Edge Cases ---

#[test]
fn classify_blockquote_without_space() {
    // `>bar` should still be a blockquote (space after > is optional)
    let s = make_streamer();
    let result = s.classify_line(">bar");
    assert_eq!(result.blockquote_depth, 1);
    assert_eq!(result.kind, BlockKind::Paragraph);
    assert_eq!(result.content, "bar");
}

#[test]
fn classify_blockquote_tab_after_marker() {
    // `>\t\tfoo` — after tab expansion, `>` followed by tab.
    // Tab at column 1 (after >) expands to 3 spaces (next tab stop at 4).
    // The blockquote regex consumes `> ` (one space), leaving `  ` + tab-expanded content.
    let s = make_streamer();
    let result = s.classify_line(">\t\tfoo");
    assert_eq!(result.blockquote_depth, 1);
    // The content after blockquote stripping should preserve the indentation from tabs
}

#[test]
fn classify_list_tab_after_marker() {
    // `-\t\tfoo` — after tab expansion: `- ` then remaining spaces + `foo`
    // The `-` marker is followed by tab-expanded spaces
    let s = make_streamer();
    let result = s.classify_line("-\t\tfoo");
    match &result.kind {
        BlockKind::ListItem { content, .. } => {
            assert!(
                content.contains("foo"),
                "List item content should contain 'foo', got: {:?}",
                content
            );
        }
        other => panic!("Expected ListItem, got: {:?}", other),
    }
}
