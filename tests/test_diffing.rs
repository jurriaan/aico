use aico::diffing::parser::StreamParser;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use tempfile::tempdir;

// --- Helpers ---

fn mock_contents(pairs: &[(&str, &str)]) -> HashMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

struct ParseResult {
    diff: String,
    items: Vec<aico::models::DisplayItem>,
    warnings: Vec<String>,
}

fn test_parse(original: &HashMap<String, String>, response: &str, root: &PathBuf) -> ParseResult {
    let mut parser = StreamParser::new(original);
    let mut processed = parser.parse_and_resolve(response, root);
    let (_, final_yields, _) = parser.finish("");
    processed.extend(parser.process_yields(final_yields, root));

    let warnings = parser.collect_warnings(&processed);
    let diff = parser.build_final_unified_diff();
    let items = processed
        .into_iter()
        .filter_map(|y| y.to_display_item(true))
        .collect();

    ParseResult {
        diff,
        items,
        warnings,
    }
}

fn analyze_diff(original: &HashMap<String, String>, response: &str, root: &PathBuf) -> String {
    test_parse(original, response, root).diff
}

fn analyze_items(
    original: &HashMap<String, String>,
    response: &str,
    root: &PathBuf,
) -> Vec<aico::models::DisplayItem> {
    test_parse(original, response, root).items
}

// --- Tests ---

#[test]
fn test_process_patches_sequentially_single_change() {
    let original = mock_contents(&[("file.py", "old content")]);
    let response =
        "File: file.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    assert!(diff.contains("-old content"));
    assert!(diff.contains("+new content"));
}

#[test]
fn test_process_patches_sequentially_failed_patch_is_captured_as_warning() {
    let original = mock_contents(&[("file.py", "original content")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nnon-existent\n=======\nnew\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let res = test_parse(&original, response, &root);
    assert_eq!(res.warnings.len(), 1);
    let warnings = res.warnings;
    assert!(warnings[0].contains("could not be found in 'file.py'"));
    assert!(warnings[0].contains("Patch skipped"));
}

#[test]
fn test_process_patches_sequentially_filesystem_fallback() {
    let temp = tempdir().unwrap();
    let root = temp.path().to_path_buf();

    // GIVEN a file on disk but empty context
    fs::write(root.join("file.py"), "disk content").unwrap();
    let original = HashMap::new();

    let response =
        "File: file.py\n<<<<<<< SEARCH\ndisk content\n=======\nnew content\n>>>>>>> REPLACE";

    let res = test_parse(&original, response, &root);
    let warnings = res.warnings;
    let diff = res.diff;

    // THEN the diff shows modification (not creation) and a warning is issued
    assert!(diff.contains("--- a/file.py"));
    assert!(diff.contains("-disk content"));
    assert!(diff.contains("+new content"));

    assert_eq!(warnings.len(), 1);
    assert!(warnings[0].contains("was not in the session context but was found on disk"));
}

#[test]
fn test_generate_diff_for_new_file_creation() {
    let original = HashMap::new();
    let response =
        "File: new_file.py\n<<<<<<< SEARCH\n=======\nprint('hello world')\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    // Note: `similar` crate unified diff output format
    assert!(diff.contains("--- /dev/null")); // or similar representation for empty
    assert!(diff.contains("+++ b/new_file.py"));
    assert!(diff.contains("+print('hello world')"));
}

#[test]
fn test_generate_diff_for_file_deletion() {
    let content = "line 1\nline 2";
    let original = mock_contents(&[("file.py", content)]);
    let response = format!(
        "File: file.py\n<<<<<<< SEARCH\n{}\n=======\n>>>>>>> REPLACE",
        content
    );
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, &response, &root);

    assert!(diff.contains("--- a/file.py"));
    assert!(diff.contains("+++ /dev/null"));
    assert!(diff.contains("-line 1"));
    assert!(diff.contains("-line 2"));
}

#[test]
fn test_generate_diff_for_filename_with_spaces() {
    let name = "my test file.py";
    let original = mock_contents(&[(name, "old")]);
    let response = format!(
        "File: {}\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
        name
    );
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, &response, &root);

    assert!(diff.contains(&format!("--- \"a/{}\"", name)));
    assert!(diff.contains(&format!("+++ \"b/{}\"", name)));
}

#[test]
fn test_whitespace_flexible_patching_succeeds() {
    // Original has 4 spaces
    let original = mock_contents(&[("file.py", "def f():\n    print('hello')\n")]);

    // Patch uses tabs/different spacing in SEARCH but matches content
    let response = "File: file.py\n<<<<<<< SEARCH\ndef f():\n\t print('hello')\n=======\ndef f():\n    print('world')\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    assert!(diff.contains("-    print('hello')"));
    assert!(diff.contains("+    print('world')"));
}

#[test]
fn test_patch_failure_when_search_block_not_found() {
    let original = mock_contents(&[("file.py", "content")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nmissing\n=======\nnew\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert_eq!(diff, "");
}

#[test]
fn test_get_consistent_indentation_utf8_safety() {
    // GIVEN lines with multi-byte whitespace characters (e.g., non-breaking space U+00A0)
    // original_content must match exactly what search expects
    let nb_space = "\u{00A0}";
    let line1 = format!("{}line1\n", nb_space);
    let line2 = format!("{}line2\n", nb_space);

    let original = mock_contents(&[("utf8.py", &format!("{}{}", line1, line2))]);

    // AND a patch that matches that indentation
    let response = format!(
        "File: utf8.py\n<<<<<<< SEARCH\n{}line1\n{}line2\n=======\n{}line1_mod\n>>>>>>> REPLACE",
        nb_space, nb_space, nb_space
    );
    let root = std::path::PathBuf::from(".");

    // WHEN the diff is generated
    let diff = analyze_diff(&original, &response, &root);

    // THEN it should succeed without panicking and produce a valid diff
    // The diff engine (similar) uses a leading space for context or -/+ for diff.
    // The nb_space is preserved, so we match against the character.
    assert!(diff.contains(&format!("-{}line1", nb_space)));
    assert!(diff.contains(&format!("+{}line1_mod", nb_space)));
}

#[test]
fn test_multi_block_llm_response_with_conversation() {
    let original = mock_contents(&[("f1.py", "one"), ("f2.py", "two")]);
    let response = "Chat.\nFile: f1.py\n<<<<<<< SEARCH\none\n=======\n1\n>>>>>>> REPLACE\nMore chat.\nFile: f2.py\n<<<<<<< SEARCH\ntwo\n=======\n2\n>>>>>>> REPLACE\nDone.";
    let root = PathBuf::from(".");

    let items = analyze_items(&original, response, &root);

    // Verify structure
    // [Markdown(Chat), Markdown(File: f1), Diff(..), Markdown(More chat), Markdown(File: f2), Diff(..), Markdown(Done)]
    let mut diff_count = 0;
    let mut all_text = String::new();
    for item in &items {
        match item {
            aico::models::DisplayItem::Markdown(s) => all_text.push_str(s),
            aico::models::DisplayItem::Diff(_) => {
                all_text.push_str("DIFF");
                diff_count += 1;
            }
        }
    }

    assert!(all_text.contains("Chat."));
    assert!(all_text.contains("More chat."));
    assert!(all_text.contains("Done."));
    assert_eq!(diff_count, 2);
}

#[test]
fn test_ambiguous_patch_succeeds_on_first_match() {
    let content = "line=1\n\nother\n\nline=1\n";
    let original = mock_contents(&[("file.py", content)]);
    let response = "File: file.py\n<<<<<<< SEARCH\nline=1\n=======\nline=2\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    // Should change first occurrence
    assert!(diff.contains("-line=1"));
    assert!(diff.contains("+line=2"));
    // 'similar' context lines will usually show 'other' if it's close enough
}

#[test]
fn test_flexible_patching_preserves_internal_relative_indentation() {
    // Original: 2 spaces base
    let original = mock_contents(&[("file.py", "  L1\n    L2\n")]);

    // Patch: Indented heavily (10 spaces), but maintains relative structure
    let response = "File: file.py\n<<<<<<< SEARCH\nL1\nL2\n=======\n          L1Mod\n            L2Mod\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    // Should result in L1Mod having 2 spaces (original base)
    // L2Mod having 4 spaces (original base 2 + relative 2)
    assert!(diff.contains("+  L1Mod"));
    assert!(diff.contains("+    L2Mod"));
}

#[test]
fn test_complex_multi_file_and_multi_patch_scenario() {
    let original = mock_contents(&[
        ("file1.py", "f1 content"),
        ("file2.py", "f2 line1\nf2 line2"),
    ]);
    let response = "File: file1.py\n<<<<<<< SEARCH\nf1 content\n=======\nf1 updated\n>>>>>>> REPLACE\n\nFile: file2.py\n<<<<<<< SEARCH\nf2 line1\n=======\nf2 line1 updated\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nf2 line2\n=======\nf2 line2 updated\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    assert!(diff.contains("file1.py"));
    assert!(diff.contains("file2.py"));
    assert!(diff.contains("+f1 updated"));
    assert!(diff.contains("+f2 line1 updated"));
    assert!(diff.contains("+f2 line2 updated"));
}

#[test]
fn test_patch_for_multi_line_indent() {
    let original = mock_contents(&[("file.py", "print('one')\nprint('two')\n")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nprint('one')\nprint('two')\n=======\ntry:\n    print('one')\n    print('two')\nexcept:\n    pass\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    assert!(diff.contains("+try:"));
    assert!(diff.contains("+    print('one')"));
    assert!(diff.contains("+    print('two')"));
}

#[test]
fn test_patching_with_blank_lines_in_search_block() {
    let original = mock_contents(&[("file.py", "a\n\nb")]);
    let response = "File: file.py\n<<<<<<< SEARCH\na\n\nb\n=======\nc\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("-a"));
    assert!(diff.contains("-b"));
    assert!(diff.contains("+c"));
}

#[test]
fn test_patching_with_trailing_blank_lines_in_search_block() {
    // GIVEN original content and a search block with trailing blank lines
    // This specifically tests that the diffing regex doesn't prematurely consume
    // the trailing newlines as part of the delimiter's whitespace.
    let original = mock_contents(&[("file.py", "code block\n\n\nsome other code")]);
    let response =
        "File: file.py\n<<<<<<< SEARCH\ncode block\n\n\n=======\nreplacement\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    // WHEN the diff is generated
    let diff = analyze_diff(&original, response, &root);

    // THEN the patch applies successfully, proving the SEARCH block was parsed correctly
    assert!(diff.contains("-code block"));
    assert!(diff.contains("+replacement"));
    assert!(diff.contains("some other code"));
}

#[test]
fn test_patch_that_changes_indentation() {
    let original = mock_contents(&[("file.py", "code()")]);
    let response =
        "File: file.py\n<<<<<<< SEARCH\ncode()\n=======\nif T:\n    code()\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("+    code()"));
}

#[test]
fn test_patch_that_outdents_code() {
    let original = mock_contents(&[("file.py", "if True:\n    code_to_outdent()\n")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nif True:\n    code_to_outdent()\n=======\ncode_to_outdent()\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("-if True:"));
    assert!(diff.contains("-    code_to_outdent()"));
    assert!(diff.contains("+code_to_outdent()"));
}

#[test]
fn test_patch_robust_to_delimiters_in_content() {
    let original = mock_contents(&[("file.py", "line_one = 1\n<<<<<<< SEARCH\nline_three = 3\n")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nline_one = 1\n<<<<<<< SEARCH\nline_three = 3\n=======\ncontent was changed\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("+content was changed"));
    assert!(diff.contains("-<<<<<<< SEARCH"));
}

#[test]
fn test_mismatched_line_endings_patch_succeeds() {
    // Original with CRLF
    let original = mock_contents(&[("file.py", "line1\r\nline2\r\n")]);
    // Response with LF (standardized by LLM)
    let response = "File: file.py\n<<<<<<< SEARCH\nline1\nline2\n=======\nnew_line1\nnew_line2\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    assert!(diff.contains("-line1"));
    assert!(diff.contains("-line2"));
    assert!(diff.contains("+new_line1"));
    assert!(diff.contains("+new_line2"));
}

#[test]
fn test_arbitrary_file_read_vulnerability_with_path_traversal() {
    let temp = tempdir().unwrap();
    let root = temp.path().join("project");
    fs::create_dir_all(&root).unwrap();

    // Secret file outside root
    let secret_path = temp.path().join("secret.txt");
    fs::write(&secret_path, "secret").unwrap();

    let original = HashMap::new();
    let response = "File: ../secret.txt\n<<<<<<< SEARCH\nsecret\n=======\nleak\n>>>>>>> REPLACE";

    let res = test_parse(&original, response, &root);

    // Should result in empty diff (no patch applied)
    assert_eq!(res.diff, "");

    // And a warning about the file not being in context/found
    assert!(
        res.warnings
            .iter()
            .any(|w| w.contains("does not match any file in context"))
    );
}

#[test]
fn test_no_newline_marker_added_for_existing_file_without_trailing_newline() {
    // GIVEN an existing file without a trailing newline and an LLM patch
    let original = mock_contents(&[("file.py", "print('old')")]);
    let response =
        "File: file.py\n<<<<<<< SEARCH\nprint('old')\n=======\nprint('new')\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    // WHEN the unified diff is generated
    let diff = analyze_diff(&original, response, &root);

    // THEN the diff should contain the "No newline" marker for the original file content
    assert!(diff.contains("-print('old')"));
    assert!(diff.contains("\\ No newline at end of file"));
    assert!(diff.contains("+print('new')"));
}

#[test]
fn test_whitespace_only_change_missing_newline_in_original() {
    // GIVEN a file with code separated by one blank line and missing final newline
    let original = mock_contents(&[("file.py", "line_one\n\nline_three")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nline_one\n\nline_three\n=======\nline_one\n\n\nline_three\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    // WHEN the diff is generated
    let diff = analyze_diff(&original, response, &root);

    // THEN the diff correctly shows the addition of one blank line and the presence of the newline fix
    assert!(diff.contains("line_one"));
    assert!(diff.contains("line_three"));
    // We check for the marker precisely. The diff engine might treat line_three as context
    // or as a change depending on optimization, but the marker MUST appear to fix the newline.
    assert!(diff.contains("\\ No newline at end of file"));
}

#[test]
fn test_no_newline_marker_not_added_for_hunk_in_middle_of_file() {
    // GIVEN a file that does not end with a newline
    let original = mock_contents(&[("file.py", "line_one\nline_two\nline_three\nfoo\n\nbar")]);

    // AND an LLM response that modifies a line in the middle of the file
    let response =
        "File: file.py\n<<<<<<< SEARCH\nline_two\n=======\nline_two_changed\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    // WHEN a diff is generated
    let diff = analyze_diff(&original, response, &root);

    // THEN the diff should NOT contain the "No newline" marker, because the
    // hunk does not include the last line of the file.
    assert!(!diff.contains("\\ No newline at end of file"));
    assert!(diff.contains("+line_two_changed"));
}

#[test]
fn test_multi_patch_on_single_file() {
    let original = mock_contents(&[("file.py", "line 1\nline 2")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nline 1\n=======\nline 1 modified\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nline 2\n=======\nline 2 modified\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("+line 1 modified"));
    assert!(diff.contains("+line 2 modified"));
    // Verify it is a single hunk or combined diff for file.py
    assert_eq!(diff.matches("--- a/file.py").count(), 1);
}

#[test]
fn test_patch_with_inconsistent_trailing_newlines() {
    let original = mock_contents(&[("file.py", "line1\nline2\n")]);
    // SEARCH block missing the final newline compared to original file content
    let response =
        "File: file.py\n<<<<<<< SEARCH\nline1\nline2\n=======\nline1\nline2_mod\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("+line2_mod"));
}

#[test]
fn test_generate_diff_for_standard_change() {
    let original = mock_contents(&[("file.py", "old_line = 1")]);
    let response =
        "File: file.py\n<<<<<<< SEARCH\nold_line = 1\n=======\nnew_line = 2\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    assert!(diff.contains("--- a/file.py"));
    assert!(diff.contains("+++ b/file.py"));
    assert!(diff.contains("-old_line = 1"));
    assert!(diff.contains("+new_line = 2"));
}

#[test]
fn test_multi_patch_with_interstitial_conversation() {
    let original = mock_contents(&[("file.py", "line 1\nline 2")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nline 1\n=======\nline one changed\n>>>>>>> REPLACE\nAnd now part two.\n<<<<<<< SEARCH\nline 2\n=======\nline two changed\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("+line one changed"));
    assert!(diff.contains("+line two changed"));
    assert!(!diff.contains("And now part two"));
}

#[test]
fn test_error_when_file_not_found_in_context_or_on_disk() {
    let original = mock_contents(&[("real.py", "content")]);
    let response = "File: unknown.py\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let res = test_parse(&original, response, &root);

    assert!(
        res.warnings
            .iter()
            .any(|w| w.contains("does not match any file in context"))
    );
}

#[test]
fn test_handling_of_malformed_llm_responses() {
    let original = HashMap::new();
    let response = "File: file.py\n<<<<<<< SEARCH\nmissing separator and terminator";

    let mut parser = StreamParser::new(&original);
    let (diff, yields, _) = parser.finish(response);
    assert_eq!(diff, "");
    // Should be markdown/text
    assert!(yields.len() >= 2);
}

#[test]
fn test_process_llm_response_stream_handles_fallback() {
    let temp = tempdir().unwrap();
    let root = temp.path().to_path_buf();
    fs::write(root.join("on_disk.py"), "disk content").unwrap();

    let original = HashMap::new();
    let response =
        "File: on_disk.py\n<<<<<<< SEARCH\ndisk content\n=======\nupdated\n>>>>>>> REPLACE";

    let res = test_parse(&original, response, &root);
    let warnings = res.warnings;
    let items = res.items;

    assert!(warnings.iter().any(|w| w.contains("found on disk")));
    assert!(
        items
            .iter()
            .any(|i| matches!(i, aico::models::DisplayItem::Diff(_)))
    );
}

#[test]
fn test_failed_patch_yields_warning_and_unparsed_block() {
    let original = mock_contents(&[("file.py", "content")]);
    let failed_block = "<<<<<<< SEARCH\nnon-existent\n=======\napplied\n>>>>>>> REPLACE";
    let response = format!("File: file.py\n{}", failed_block);
    let root = PathBuf::from(".");

    let res = test_parse(&original, &response, &root);
    let warnings = res.warnings;
    let items = res.items;

    assert!(
        warnings
            .iter()
            .any(|w| w.contains("could not be found in 'file.py'"))
    );
    assert!(items.iter().any(|i| match i {
        aico::models::DisplayItem::Markdown(t) =>
            t.contains("<<<<<<< SEARCH") && t.contains(">>>>>>> REPLACE"),
        _ => false,
    }));
}

#[test]
fn test_process_patches_sequentially_multiple_changes() {
    let original = mock_contents(&[("file.py", "line 1\nline 2")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nline 1\n=======\nline one\n>>>>>>> REPLACE\n\nSome chat.\n\nFile: file.py\n<<<<<<< SEARCH\nline 2\n=======\nline two\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    assert!(diff.contains("-line 1"));
    assert!(diff.contains("+line one"));
    assert!(diff.contains("-line 2"));
    assert!(diff.contains("+line two"));
}

#[test]
fn test_whitespace_only_change() {
    let original = mock_contents(&[("file.py", "line_one\n\nline_three\n")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nline_one\n\nline_three\n=======\nline_one\n\n\nline_three\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    // Should show the addition of a blank line.
    assert!(diff.contains("+"));
    assert!(diff.contains("line_one"));
    assert!(diff.contains("line_three"));
}

#[test]
fn test_generate_diff_with_filesystem_fallback() {
    let temp = tempdir().unwrap();
    let root = temp.path().to_path_buf();
    fs::write(root.join("fallback.py"), "original").unwrap();

    let original = HashMap::new();
    let response = "File: fallback.py\n<<<<<<< SEARCH\noriginal\n=======\nnew\n>>>>>>> REPLACE";

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("--- a/fallback.py"));
    assert!(diff.contains("-original"));
    assert!(diff.contains("+new"));
}

#[test]
fn test_newline_logic_consumes_trailing_newline_for_new_files() {
    // GIVEN a patch where the REPLACE block in the string literal looks like "new content\n"
    // before the marker line.
    // Python/Fixed-Rust behavior: The parser consumes the newline, so the file has a trailing newline.
    let original = HashMap::new();
    let response = "File: new.py\n<<<<<<< SEARCH\n=======\nnew content\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    // WHEN the diff is generated
    let diff = analyze_diff(&original, response, &root);

    // THEN the diff shows the new content
    assert!(diff.contains("--- /dev/null"));
    assert!(diff.contains("+++ b/new.py"));
    assert!(diff.contains("+new content"));
    // AND it should NOT contain the "No newline" marker because the parser included the implicit newline.
    assert!(!diff.contains("\\ No newline at end of file"));
}

#[test]
fn test_newline_logic_consumes_trailing_newline_for_empty_file_update() {
    // GIVEN a patch to update an empty file
    let original = mock_contents(&[("new.py", "")]);
    let response = "File: new.py\n<<<<<<< SEARCH\n=======\nnew content\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    // WHEN the diff is generated
    let diff = analyze_diff(&original, response, &root);

    // THEN the diff is produced cleanly with a trailing newline
    assert!(diff.contains("--- a/new.py"));
    assert!(diff.contains("+++ b/new.py"));
    assert!(diff.contains("+new content"));
    assert!(!diff.contains("\\ No newline at end of file"));
}

#[test]
fn test_flexible_patching_reproduction_uneven_indentation() {
    // Forces the flexible patcher to handle a block where the first line
    // has a different indentation than the common denominator of the block.
    let original = mock_contents(&[("file.py", "    def func():\n        pass\n")]);

    // AND an LLM response with a whitespace mismatch in SEARCH
    // AND a REPLACE block where the first line is indented MORE than the second line.
    let response = "File: file.py\n<<<<<<< SEARCH\ndef func():\n    pass\n=======\n          def renamed():\n    pass\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    // WHEN the diff is generated
    let diff = analyze_diff(&original, response, &root);

    // THEN the patch should succeed and preserve the relative structure.
    // The original base was 4 spaces.
    // Replace Min Indent = 4 spaces.
    // Line 1 (10 spaces) -> relative +6.
    // Line 1 Result: Original Base (4) + 6 = 10 spaces.
    assert!(diff.contains("+          def renamed():"));
    assert!(diff.contains("+    pass"));
}

#[test]
fn test_predictability_no_fuzzy_matching_on_paths() {
    // GIVEN a context containing one file
    let original = mock_contents(&[("src/models/ai.py", "class AI: pass")]);
    // AND an LLM response that targets a different but similarly named file
    let response = "File: src/models/dto/ai.py\n<<<<<<< SEARCH\nclass DTO_AI: pass\n=======\nclass DTO_AI_MODIFIED: pass\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    // WHEN the diff is generated
    let diff = analyze_diff(&original, response, &root);

    // THEN the diff is empty because the patch failed (file not found)
    assert_eq!(diff, "");
}

#[test]
fn test_partial_deletion_inside_file() {
    let original = mock_contents(&[(
        "file.py",
        "def my_func():\n    line_one = 1\n    line_two = 2\n    line_three = 3\n",
    )]);
    let response = "File: file.py\n<<<<<<< SEARCH\n    line_one = 1\n    line_two = 2\n=======\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);

    assert!(diff.contains("def my_func()"));
    assert!(diff.contains("-    line_one = 1"));
    assert!(diff.contains("-    line_two = 2"));
    assert!(diff.contains("    line_three = 3"));
}

#[test]
fn test_empty_search_on_existing_file_fails() {
    let original = mock_contents(&[("file.py", "some_content = True")]);
    let response = "File: file.py\n<<<<<<< SEARCH\n=======\nnew_content = False\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert_eq!(diff, "");
}

#[test]
fn test_whitespace_only_search_block_fails_cleanly() {
    let original = mock_contents(&[("file.py", "line_one\n\n\nline_two")]);
    let response = "File: file.py\n<<<<<<< SEARCH\n \n \n=======\nsome_content\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert_eq!(diff, "");
}

#[test]
fn test_generate_diff_for_new_empty_file_followed_by_another_file() {
    let original = HashMap::new();
    let response = "File: app/__init__.py\n<<<<<<< SEARCH\n=======\n>>>>>>> REPLACE\n\nFile: app/renderer.py\n<<<<<<< SEARCH\n=======\nimport html\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("--- /dev/null\n+++ b/app/__init__.py"));
    assert!(diff.contains("--- /dev/null\n+++ b/app/renderer.py"));
    assert!(diff.contains("+import html"));
}

#[test]
fn test_generate_display_items_from_conversation_only() {
    let original = mock_contents(&[("file.py", "content")]);
    let response = "I'm not sure how to make that change. Could you clarify?";
    let root = PathBuf::from(".");

    let items = analyze_items(&original, response, &root);
    assert_eq!(items.len(), 1);
    match &items[0] {
        aico::models::DisplayItem::Markdown(s) => assert_eq!(s, response),
        _ => panic!("Expected markdown item"),
    }
}

#[test]
fn test_generate_display_items_malformed_block() {
    let original = HashMap::new();
    let response =
        "File: file.py\nThis is not a valid diff block because it's missing the delimiters.";
    let root = PathBuf::from(".");

    let items = analyze_items(&original, response, &root);
    // Should be treated as two markdown chunks because the "File:" line is matched by file_header_re
    assert!(items.len() >= 2);
}

#[test]
fn test_generate_display_items_with_conversation() {
    let original = mock_contents(&[("file.py", "old_line")]);
    let response =
        "Hello!\nFile: file.py\n<<<<<<< SEARCH\nold_line\n=======\nnew_line\n>>>>>>> REPLACE\nBye!";
    let root = PathBuf::from(".");

    let items = analyze_items(&original, response, &root);
    assert!(items.iter().any(|i| match i {
        aico::models::DisplayItem::Markdown(s) => s.contains("Hello!"),
        _ => false,
    }));
    assert!(items.iter().any(|i| match i {
        aico::models::DisplayItem::Diff(_) => true,
        _ => false,
    }));
    assert!(items.iter().any(|i| match i {
        aico::models::DisplayItem::Markdown(s) => s.contains("Bye!"),
        _ => false,
    }));
}

#[test]
fn test_parser_is_robust_to_formatting_for_diff() {
    let original = mock_contents(&[("file.py", "old")]);
    let response =
        "  File: file.py  \n  <<<<<<< SEARCH\n  old\n  =======\n  new\n  >>>>>>> REPLACE  ";
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert!(diff.contains("-old"));
    assert!(diff.contains("+new"));
}

#[test]
fn test_parser_is_robust_to_formatting_for_display_items() {
    let original = mock_contents(&[("file.py", "old")]);
    let response = "  File: file.py\n  <<<<<<< SEARCH\n  old\n  =======\n  new\n  >>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let items = analyze_items(&original, response, &root);
    assert!(
        items
            .iter()
            .any(|i| matches!(i, aico::models::DisplayItem::Diff(_)))
    );
}

#[test]
fn test_parser_preserves_interstitial_conversation_and_newlines() {
    let original = mock_contents(&[("f1.py", "c1"), ("f2.py", "c2")]);
    let response = "File: f1.py\n<<<<<<< SEARCH\nc1\n=======\nn1\n>>>>>>> REPLACE\n\n\nInter\n\n\nFile: f2.py\n<<<<<<< SEARCH\nc2\n=======\nn2\n>>>>>>> REPLACE";
    let root = PathBuf::from(".");

    let items = analyze_items(&original, response, &root);
    let all_text: String = items
        .iter()
        .map(|i| match i {
            aico::models::DisplayItem::Markdown(s) => s.clone(),
            _ => "".to_string(),
        })
        .collect();

    // Parity check: Python parser emits interstitial text exactly.
    // In Rust, if REPLACE consumed its newline, the \n\n\nInter\n\n\n follows it precisely.
    assert!(all_text.contains("\n\n\nInter\n\n\n"));
}

#[test]
fn test_generate_diff_torture_filenames() {
    // Filename with spaces, quotes, and tabs (though tabs are often escaped/forbidden in some FS)
    let name = "dir/my \"file\" name.txt";
    let original = mock_contents(&[(name, "original")]);
    let response = format!(
        "File: {}\n<<<<<<< SEARCH\noriginal\n=======\nupdated\n>>>>>>> REPLACE",
        name
    );
    let root = PathBuf::from(".");

    let diff = analyze_diff(&original, &response, &root);

    // Verify quoting parity with Python
    assert!(diff.contains(&format!("--- \"a/{}\"", name)));
    assert!(diff.contains(&format!("+++ \"b/{}\"", name)));
    assert!(diff.contains("-original"));
    assert!(diff.contains("+updated"));
}

#[test]
fn test_patch_does_not_panic_on_short_original() {
    let original = mock_contents(&[("file.py", "only one line")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nonly one line\nand another missing line\n=======\nshould not matter\n>>>>>>> REPLACE";
    let root = std::path::PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert_eq!(diff, "");
}

#[test]
fn test_patch_exact_match_shorter_than_search_does_not_panic() {
    let original = mock_contents(&[("file.py", "line1")]);
    let response = "File: file.py\n<<<<<<< SEARCH\nline1\nline2\n=======\nnew\n>>>>>>> REPLACE";
    let root = std::path::PathBuf::from(".");

    let diff = analyze_diff(&original, response, &root);
    assert_eq!(diff, "");
}
