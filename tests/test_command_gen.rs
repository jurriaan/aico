use assert_cmd::cargo::cargo_bin_cmd;
use mockito::{Matcher, Server};
use predicates::prelude::*;
use serde_json::json;
use std::fs;
use tempfile::tempdir;

fn setup_session(root: &std::path::Path) {
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();
}

#[tokio::test]
async fn test_gen_command_outputs_diff_and_saves_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    // GIVEN a file in context
    let file_path = root.join("file.py");
    // Write without trailing newline to match expected_context_block exactly
    fs::write(&file_path, "old content").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file.py"])
        .assert()
        .success();

    // AND a mock OpenAI server
    let mut server = Server::new_async().await;

    let llm_response =
        "File: file.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE";

    let chunk = json!({
        "choices": [{"delta": {"content": llm_response}, "index": 0, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}
    });

    let mut expected_messages = vec![
        json!({ "role": "system", "content": format!("{}{}", aico::consts::DEFAULT_SYSTEM_PROMPT, aico::consts::DIFF_MODE_INSTRUCTIONS) }),
    ];
    // Context block
    let expected_context_block =
        "<context>\n  <file path=\"file.py\">\nold content\n  </file>\n</context>";
    expected_messages.push(json!({ "role": "user", "content": format!("{}\n\n{}", aico::consts::STATIC_CONTEXT_INTRO, expected_context_block) }));
    expected_messages
        .push(json!({ "role": "assistant", "content": aico::consts::STATIC_CONTEXT_ANCHOR }));
    // Alignment
    expected_messages.push(json!({ "role": "user", "content": aico::consts::ALIGNMENT_DIFF_USER }));
    expected_messages
        .push(json!({ "role": "assistant", "content": aico::consts::ALIGNMENT_DIFF_ASSISTANT }));
    // Prompt
    expected_messages.push(json!({ "role": "user", "content": "Update the file" }));

    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(json!({
            "model": "test-model",
            "messages": expected_messages,
            "stream": true,
            "stream_options": { "include_usage": true }
        })))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    // WHEN running `aico gen`
    let mut cmd = cargo_bin_cmd!("aico");
    cmd.current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "Update the file"])
        .assert()
        .success()
        // THEN stdout contains the Unified Diff
        .stdout(predicate::str::contains("--- a/file.py"))
        .stdout(predicate::str::contains("+++ b/file.py"))
        .stdout(predicate::str::contains("-old content"))
        .stdout(predicate::str::contains("+new content"));

    mock.assert_async().await;

    // VERIFY: History saved with diff mode and derived content
    let store_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(store_path).unwrap();
    assert!(content.contains("\"mode\":\"diff\""));
    assert!(content.contains("\"unified_diff\":\"--- a/file.py"));
}

#[tokio::test]
async fn test_gen_successful_diff_piped() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    // GIVEN a file in context
    let file_path = root.join("app.py");
    fs::write(&file_path, "def main():\n    pass\n").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "app.py"])
        .assert()
        .success();

    // AND a mock server returning a diff wrapped in conversational text
    let mut server = Server::new_async().await;
    let llm_response = "I have updated the code.\n\nFile: app.py\n<<<<<<< SEARCH\n    pass\n=======\n    print('done')\n>>>>>>> REPLACE\n\nHope this helps!";

    let chunk = json!({
        "choices": [{"delta": {"content": llm_response}, "index": 0}],
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    // WHEN running `aico gen` (assert_cmd/cargo_bin_cmd does not attach a TTY by default)
    let mut cmd = cargo_bin_cmd!("aico");
    cmd.current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "add print"])
        .assert()
        .success()
        // THEN stdout contains ONLY the clean Unified Diff (composable I/O)
        .stdout(predicate::str::contains("--- a/app.py"))
        .stdout(predicate::str::contains("-    pass"))
        .stdout(predicate::str::contains("+    print('done')"))
        // AND none of the conversational "garbage"
        .stdout(predicate::str::contains("I have updated the code").not())
        .stdout(predicate::str::contains("Hope this helps").not());

    mock.assert_async().await;
}

#[tokio::test]
async fn test_gen_history_is_clean_of_partial_markers() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let file_path = root.join("test.py");
    fs::write(&file_path, "old_code\n").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "test.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;

    // Chunk 1: Header + Partial Marker
    let chunk1 = json!({
        "choices": [{"delta": {"content": "File: test.py\n<<<<"}, "index": 0}]
    });
    // Chunk 2: Completion
    let chunk2 = json!({
        "choices": [{"delta": {"content": "<<< SEARCH\nold_code\n=======\nnew_code\n>>>>>>> REPLACE"}, "index": 0}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: {}\n\ndata: [DONE]\n\n",
            serde_json::to_string(&chunk1).unwrap(),
            serde_json::to_string(&chunk2).unwrap()
        ))
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "fix it"])
        .assert()
        .success();

    mock.assert_async().await;

    // VERIFY: History must NOT contain the ephemeral "<<<<" fragment
    let store_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(store_path).unwrap();
    assert!(
        !content.contains(r#"{"type":"markdown","content":"<<<<"}"#),
        "History contains leaked ephemeral buffer content: {}",
        content
    );
}

#[tokio::test]
async fn test_gen_ui_deduplication_and_derived_integrity() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let file_path = root.join("logic.py");
    fs::write(&file_path, "def run():\n    return False\n").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "logic.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;

    // Simulate a stream that splits exactly at a marker boundary to test the buffer logic
    let chunk1 = json!({
        "choices": [{"delta": {"content": "Applying fix...\n\nFile: logic.py\n<<<<<<<"}, "index": 0}]
    });
    let chunk2 = json!({
        "choices": [{"delta": {"content": " SEARCH\n    return False\n=======\n    return True\n>>>>>>> REPLACE\nDone!"}, "index": 0}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: {}\n\ndata: [DONE]\n\n",
            serde_json::to_string(&chunk1).unwrap(),
            serde_json::to_string(&chunk2).unwrap()
        ))
        .create_async()
        .await;

    // Execute gen
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "make it true"])
        .assert()
        .success()
        // 1. Check stdout contains the clean diff
        .stdout(predicate::str::contains("+    return True"))
        // 2. CRITICAL: Check stdout does NOT contain the raw marker leaked from the buffer
        .stdout(predicate::str::contains("<<<<<<< SEARCH").not());

    mock.assert_async().await;

    // 3. Verify History Integrity via 'last --json'
    let last_json = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let parsed: serde_json::Value = serde_json::from_slice(&last_json).unwrap();
    let display_items = parsed["assistant"]["derived"]["display_content"]
        .as_array()
        .expect("display_content should be an array");

    // Ensure we have a Markdown item for "Applying fix...", a Diff item, and "Done!"
    // But NO Markdown item containing the markers.
    let has_raw_marker_in_history = display_items.iter().any(|item| {
        item["content"]
            .as_str()
            .map_or(false, |c| c.contains("<<<<<<<"))
    });

    assert!(
        !has_raw_marker_in_history,
        "Raw SEARCH markers leaked into history records!"
    );
}

#[tokio::test]
async fn test_gen_failed_patch_prints_warning_stderr() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // Response that fails to apply (search block mismatch)
    let llm_response = "File: missing.py\n<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE";

    let chunk = json!({
        "choices": [{"delta": {"content": llm_response}, "index": 0}],
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    // WHEN running gen
    let mut cmd = cargo_bin_cmd!("aico");
    cmd.current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "Fix it"])
        .assert()
        .success()
        // THEN stdout is empty for a failed patch in gen mode (Strict Contract)
        .stdout(predicate::str::is_empty())
        // AND stderr has warning
        .stderr(predicate::str::contains("Warnings:"))
        .stderr(predicate::str::contains(
            "File 'missing.py' from the AI does not match",
        ));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_gen_failed_patch_is_fenced_in_output() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // Response that fails to apply (search block mismatch)
    let llm_response = "File: missing.py\n<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE";

    let chunk = json!({
        "choices": [{"delta": {"content": llm_response}, "index": 0}],
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    // Use AICO_WIDTH/HEIGHT to simulate TTY to ensure we go through LiveDisplay path
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .env("AICO_WIDTH", "80")
        .env("AICO_FORCE_TTY", "1")
        .args(["gen", "Fix it"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    // Verify literal rendering by stripping ANSI codes
    let clean_stdout = aico::console::strip_ansi_codes(&String::from_utf8_lossy(&output));

    // Check for the full search block in one go to ensure markers and content aren't corrupted or split
    let expected_literal_block = "<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE";

    // We normalize spaces in the search because MarkdownStreamer might add trailing
    // spaces for background color padding, but the line content must match.
    let clean_lines: Vec<String> = clean_stdout.lines().map(|l| l.trim().to_string()).collect();

    let expected_lines: Vec<&str> = expected_literal_block.lines().collect();

    // Find the sequence of lines in the output
    let found_match = clean_lines.windows(expected_lines.len()).any(|window| {
        window
            .iter()
            .zip(expected_lines.iter())
            .all(|(actual, expected)| actual == expected)
    });

    assert!(
        found_match,
        "Could not find the literal SEARCH/REPLACE block in stdout:\n{}",
        clean_stdout
    );

    // Ensure it is NOT parsed as a blockquote (the │ character comes from MarkdownStreamer's blockquote logic)
    assert!(
        !clean_stdout.contains('│'),
        "Output appears to be parsed as a blockquote:\n{}",
        clean_stdout
    );

    mock.assert_async().await;
}

#[tokio::test]
async fn test_gen_missing_context_file_reports_warning_to_stderr() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    // GIVEN a file added to context
    let file_path = root.join("missing_on_disk.py");
    fs::write(&file_path, "content").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "missing_on_disk.py"])
        .assert()
        .success();

    // AND then the file is deleted from disk
    fs::remove_file(&file_path).unwrap();

    // AND a mock server
    let mut server = Server::new_async().await;
    let chunk = json!({
        "choices": [{"delta": {"content": "I can't see the file."}, "index": 0}],
    });
    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    // WHEN running gen
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "Fix the missing file"])
        .assert()
        .success()
        // THEN stderr contains the warning about the missing file
        .stderr(predicate::str::contains(
            "Warning: Context files not found on disk: missing_on_disk.py",
        ));

    mock.assert_async().await;
}
