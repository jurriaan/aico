mod common;
use crate::common::setup_session;
use assert_cmd::cargo::cargo_bin_cmd;
use mockito::{Matcher, Server};
use serde_json::json;
use std::fs;
use tempfile::tempdir;

#[tokio::test]
async fn test_gen_command_with_filesystem_fallback_and_warning() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    // GIVEN a file on disk but NOT in context
    let file_path = root.join("on_disk.py");
    fs::write(&file_path, "original line").unwrap();

    let mut server = Server::new_async().await;
    let llm_diff =
        "File: on_disk.py\n<<<<<<< SEARCH\noriginal line\n=======\nnew line\n>>>>>>> REPLACE";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_diff}}]})
        ))
        .create_async()
        .await;

    // WHEN running gen
    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "patch on_disk"])
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();
    let stderr = String::from_utf8(output.stderr.clone()).unwrap();

    // THEN it found the file on disk (fallback) and generated a diff
    assert!(stdout.contains("--- a/on_disk.py"));
    assert!(stdout.contains("-original line"));
    assert!(stdout.contains("+new line"));

    // AND it warned about the fallback
    assert!(stderr.contains("Warnings:"));
    assert!(stderr.contains("was not in the session context but was found on disk"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_streaming_handles_multiple_patches_for_same_file_piped() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    let file_path = root.join("multi.py");
    fs::write(&file_path, "line1\nline2\nline3\n").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "multi.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    // Two separate patches for the same file in one response
    let llm_response = "File: multi.py\n<<<<<<< SEARCH\nline1\n=======\nmod1\n>>>>>>> REPLACE\n\nFile: multi.py\n<<<<<<< SEARCH\nline3\n=======\nmod3\n>>>>>>> REPLACE";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_response}}]})
        ))
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "multi patch"])
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();

    // Check for combined unified diff
    assert!(stdout.contains("--- a/multi.py"));
    assert!(stdout.contains("-line1"));
    assert!(stdout.contains("+mod1"));
    assert!(stdout.contains("-line3"));
    assert!(stdout.contains("+mod3"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_streaming_renders_incomplete_diff_block_as_plain_text() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    let mut server = Server::new_async().await;
    // Cuts off right before REPLACE
    let llm_incomplete = "File: file.py\n<<<<<<< SEARCH\nold\n=======\nnew";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_incomplete}}]})
        ))
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "cut off"])
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();

    // In ASK mode, non-TTY, it should fallback to content since diffing failed
    assert!(stdout.contains("<<<<<<< SEARCH"));
    assert!(stdout.contains("new"));
    assert!(!stdout.contains("--- a/file.py"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_streaming_renders_failed_diff_block_as_plain_text() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    let file_path = root.join("mismatch.py");
    fs::write(&file_path, "actual content").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "mismatch.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    // SEARCH block does not match file content
    let llm_mismatch =
        "File: mismatch.py\n<<<<<<< SEARCH\nwrong content\n=======\nnew content\n>>>>>>> REPLACE";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_mismatch}}]})
        ))
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "mismatch"])
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();
    let stderr = String::from_utf8(output.stderr.clone()).unwrap();

    // Fallback to plain text in stdout for ASK mode
    assert!(stdout.contains("<<<<<<< SEARCH"));
    assert!(stdout.contains("wrong content"));

    // Warning in stderr
    assert!(stderr.contains("Warnings:"));
    assert!(stderr.contains("SEARCH block from the AI could not be found"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_streaming_handles_multiple_patches_for_same_file_tty() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    let file_path = root.join("code.py");
    fs::write(&file_path, "line1\nline2\nline3\n").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "code.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let llm_resp = "File: code.py\n<<<<<<< SEARCH\nline1\n=======\nMOD1\n>>>>>>> REPLACE\n\nFile: code.py\n<<<<<<< SEARCH\nline3\n=======\nMOD3\n>>>>>>> REPLACE";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_resp}}]})
        ))
        .create_async()
        .await;

    // Force TTY mode to trigger Markdown/Live rendering instead of raw Unified Diff
    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .env("AICO_FORCE_TTY", "1")
        .args(["gen", "multi"])
        .assert()
        .success();

    let raw_stdout = String::from_utf8(assert.get_output().stdout.clone()).unwrap();
    let stdout = aico::console::strip_ansi_codes(&raw_stdout);

    // In TTY mode, it should render Markdown headers alongside unified diff headers
    assert!(stdout.contains("File: code.py"));
    assert!(stdout.contains("--- a/code.py"));
    assert!(stdout.contains("-line1"));
    assert!(stdout.contains("+MOD1"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_tty_rendering_integrity_and_spacing() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    // Create the file so it can be matched by the diff engine to avoid warnings
    fs::write(root.join("test.py"), "old\n").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "test.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let llm_resp = "File: `test.py`\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_resp}}]}),
            json!({
                "choices": [],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150
                }
            })
        ))
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .env("AICO_FORCE_TTY", "1")
        .args(["gen", "test"])
        .assert()
        .success();

    let raw_stdout = String::from_utf8(assert.get_output().stdout.clone()).unwrap();
    let raw_stderr = String::from_utf8(assert.get_output().stderr.clone()).unwrap();
    let stdout = aico::console::strip_ansi_codes(&raw_stdout);

    // 1. Verify content in backticks is visible (implementation fix)
    assert!(stdout.contains("File: test.py"));

    // 2. Verify cost summary prefix
    // The cost summary prefix "---" is written to stderr.
    // Strip ANSI codes before checking lines as .dim() adds them in TTY mode.
    let clean_stderr = aico::console::strip_ansi_codes(&raw_stderr);
    let stderr_lines: Vec<&str> = clean_stderr
        .lines()
        .map(|l| l.trim())
        .filter(|l| !l.is_empty())
        .collect();

    // The dashes are the second to last line (last line is the token info)
    assert!(
        stderr_lines.len() >= 2,
        "Expected at least 2 lines in stderr (dashes and usage), got: {:?}",
        stderr_lines
    );
    assert_eq!(stderr_lines[stderr_lines.len() - 2], "---");

    mock.assert_async().await;
}

#[tokio::test]
async fn test_ask_command_invokes_correct_mode() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let _mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Any)
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "test"])
        .assert()
        .success();

    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"mode\":\"conversation\""));
}

#[tokio::test]
async fn test_gen_commands_invoke_correct_mode() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let _mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "test"])
        .assert()
        .success();

    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"mode\":\"diff\""));
}

#[tokio::test]
async fn test_prompt_defaults_to_raw_mode() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(json!({
            "model": "test-model",
            "messages": [
                { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
                { "role": "user", "content": "raw prompt" }
            ],
            "stream": true,
            "stream_options": { "include_usage": true }
        })))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "--passthrough", "raw prompt"])
        .assert()
        .success();

    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"passthrough\":true"));
    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_input_scenarios() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            {
                "role": "user",
                "content": "<stdin_content>\nhello\n</stdin_content>\n<prompt>\nworld\n</prompt>"
            }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: {}\n\ndata: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "world"])
        .write_stdin("hello")
        .assert()
        .success();

    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_with_history_reconstructs_piped_content() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let mock1 = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: {\"choices\":[{\"delta\":{\"content\":\"resp 1\"}}]}\n\ndata: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "cli 1"])
        .write_stdin("pipe 1")
        .assert()
        .success();
    mock1.assert_async().await;

    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            {
                "role": "user",
                "content": "<stdin_content>\npipe 1\n</stdin_content>\n<prompt>\ncli 1\n</prompt>"
            },
            { "role": "assistant", "content": "resp 1" },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            { "role": "user", "content": "cli 2" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock2 = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: {}\n\ndata: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "cli 2"])
        .assert()
        .success();

    mock2.assert_async().await;
}

#[tokio::test]
async fn test_ask_command_with_diff_response_outputs_diff_non_tty() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let file_path = root.join("app.py");
    fs::write(&file_path, "def main(): pass").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "app.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let llm_diff = "File: app.py\n<<<<<<< SEARCH\ndef main(): pass\n=======\ndef main(): print('hello')\n>>>>>>> REPLACE";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_diff}}]})
        ))
        .create_async()
        .await;

    // WHEN running ask in piped mode
    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "change"])
        .assert()
        .success();

    // THEN Flexible Contract: Converts to Unified Diff in stdout
    let stdout = String::from_utf8(assert.get_output().stdout.clone()).unwrap();
    assert!(stdout.contains("--- a/app.py"));
    assert!(stdout.contains("+def main(): print('hello')"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_gen_command_generates_diff() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let file_path = root.join("file.py");
    fs::write(&file_path, "content").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let llm_resp = "File: file.py\n<<<<<<< SEARCH\ncontent\n=======\nupdated\n>>>>>>> REPLACE";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_resp}}]})
        ))
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "fix it"])
        .assert()
        .success();

    let stdout = String::from_utf8(assert.get_output().stdout.clone()).unwrap();
    assert!(stdout.contains("--- a/file.py"));
    assert!(stdout.contains("-content"));
    assert!(stdout.contains("+updated"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_command_raw_mode_no_alignment() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    // Passthrough should skip alignment and XML context
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": "raw prompt" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "--passthrough", "raw prompt"])
        .assert()
        .success();

    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_with_history_reconstructs_piped_content_reproduction() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let mock1 = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: {\"choices\":[{\"delta\":{\"content\":\"resp 1\"}}]}\n\ndata: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "cli prompt"])
        .write_stdin("piped pipe")
        .assert()
        .success();
    mock1.assert_async().await;

    // Turn 2 should reconstruct Turn 1 as XML
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            {
                "role": "user",
                "content": "<stdin_content>\npiped pipe\n</stdin_content>\n<prompt>\ncli prompt\n</prompt>"
            },
            { "role": "assistant", "content": "resp 1" },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            { "role": "user", "content": "Second" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock2 = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: {}\n\ndata: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "Second"])
        .assert()
        .success();

    mock2.assert_async().await;
}

#[tokio::test]
async fn test_ask_command_injects_alignment() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            { "role": "user", "content": "ping" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "ping"])
        .assert()
        .success();

    mock.assert_async().await;
}

#[tokio::test]
async fn test_gen_command_generates_diff_alignment() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": format!("{}{}", aico::consts::DEFAULT_SYSTEM_PROMPT, aico::consts::DIFF_MODE_INSTRUCTIONS) },
            { "role": "user", "content": aico::consts::ALIGNMENT_DIFF_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_DIFF_ASSISTANT },
            { "role": "user", "content": "fix" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "fix"])
        .assert()
        .success();

    mock.assert_async().await;
}

#[tokio::test]
async fn test_ask_command_invokes_conversation_mode() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let _mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Any)
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "test"])
        .assert()
        .success();

    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"mode\":\"conversation\""));
}

#[tokio::test]
async fn test_gen_command_invokes_diff_mode() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let _mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "test"])
        .assert()
        .success();

    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"mode\":\"diff\""));
}

#[tokio::test]
async fn test_ask_successful_diff_piped() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let file_path = root.join("app.py");
    fs::write(&file_path, "old content").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "app.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let llm_diff =
        "File: app.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE";

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: [DONE]\n\n",
            json!({"choices": [{"delta": {"content": llm_diff}}]})
        ))
        .create_async()
        .await;

    // WHEN running ask in piped mode
    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "change"])
        .assert()
        .success();

    // THEN it converts to Unified Diff for stdout
    let stdout = String::from_utf8(assert.get_output().stdout.clone()).unwrap();
    assert!(stdout.contains("--- a/app.py"));
    assert!(stdout.contains("-old content"));
    assert!(stdout.contains("+new content"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_uses_session_default_model_when_not_overridden() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // Init with a specific model
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "openai/gpt-custom"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::PartialJson(json!({
            "model": "gpt-custom"
        })))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "hello"])
        .assert()
        .success();

    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_input_scenarios_piped_only() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            { "role": "user", "content": "pipe only" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .arg("ask")
        .write_stdin("pipe only")
        .assert()
        .success();

    mock.assert_async().await;
}
