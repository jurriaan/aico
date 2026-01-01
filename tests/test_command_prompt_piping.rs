mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use mockito::{Matcher, Server};
use serde_json::json;
use std::fs;
use tempfile::tempdir;

#[tokio::test]
async fn test_prompt_input_scenarios_both_cli_and_piped() {
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

    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            {
                "role": "user",
                "content": "<stdin_content>\npipe in\n</stdin_content>\n<prompt>\ncli arg\n</prompt>"
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
        .args(["ask", "cli arg"])
        .write_stdin("pipe in")
        .assert()
        .success();

    mock.assert_async().await;

    // Verify history saved both components
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"content\":\"cli arg\""));
    assert!(content.contains("\"piped_content\":\"pipe in\""));
}

#[tokio::test]
async fn test_ask_successful_diff_piped_flexible_contract() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    let file_path = root.join("app.py");
    fs::write(&file_path, "old content").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "app.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let llm_diff = "I updated the file.\n\nFile: app.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE";

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

    // THEN it converts to Unified Diff for stdout in preference to text
    let stdout = String::from_utf8(assert.get_output().stdout.clone()).unwrap();
    assert!(stdout.contains("--- a/app.py"));
    assert!(stdout.contains("-old content"));
    assert!(stdout.contains("+new content"));
    // Conversational garbage is stripped from stdout in piping mode if a diff is present
    assert!(!stdout.contains("I updated the file"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_gen_command_generates_diff_non_tty() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();

    let file_path = root.join("file.py");
    fs::write(&file_path, "old line").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let llm_diff = "Update!\n\nFile: file.py\n<<<<<<< SEARCH\nold line\n=======\nnew line\n>>>>>>> REPLACE\n\nLater!";

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

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "make change"])
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();

    // Strict contract: ONLY diff in stdout
    assert!(stdout.contains("--- a/file.py"));
    assert!(stdout.contains("+new line"));
    assert!(!stdout.contains("Update!"));
    assert!(!stdout.contains("Later!"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_with_history_reconstructs_piped_content_correctly() {
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

    // First turn with piped input
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
        .args(["ask", "first cli"])
        .write_stdin("first pipe")
        .assert()
        .success();
    mock1.assert_async().await;

    // Second turn: Verify the previous turn is reconstructed with XML
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            {
                "role": "user",
                "content": "<stdin_content>\nfirst pipe\n</stdin_content>\n<prompt>\nfirst cli\n</prompt>"
            },
            { "role": "assistant", "content": "resp 1" },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            { "role": "user", "content": "second prompt" }
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
        .args(["ask", "second prompt"])
        .assert()
        .success();

    mock2.assert_async().await;
}

#[tokio::test]
async fn test_ask_conversational_text_piped() {
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
    let llm_text = "This is a conversational response.";

    let body = json!({
        "choices": [{"delta": {"content": llm_text}}]
    });
    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", body))
        .create_async()
        .await;

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "say something"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    assert_eq!(String::from_utf8(output).unwrap().trim(), llm_text);
    mock.assert_async().await;
}

#[tokio::test]
async fn test_ask_failing_diff_piped() {
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
    // Search block doesn't exist on disk
    let llm_response =
        "File: non-existent.py\n<<<<<<< SEARCH\nmissing\n=======\nnew\n>>>>>>> REPLACE";

    let body = json!({
        "choices": [{"delta": {"content": llm_response}}]
    });
    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", body))
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "change file"])
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();
    let stderr = String::from_utf8(output.stderr.clone()).unwrap();

    // Flexible contract: If diff fails in ASK mode, print raw text/warnings to user
    assert!(stdout.contains("<<<<<<< SEARCH"));
    assert!(stderr.contains("Warnings:"));
    assert!(stderr.contains("File 'non-existent.py' from the AI does not match"));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_gen_failing_diff_piped() {
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
    let llm_response =
        "File: non-existent.py\n<<<<<<< SEARCH\nmissing\n=======\nnew\n>>>>>>> REPLACE";

    let body = json!({
        "choices": [{"delta": {"content": llm_response}}]
    });
    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", body))
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["gen", "change file"])
        .assert()
        .success();

    let output = assert.get_output();
    // Strict contract: If diff fails in GEN mode, stdout must be EMPTY to avoid corrupting patch pipes
    assert!(output.stdout.is_empty());
    assert!(
        String::from_utf8(output.stderr.clone())
            .unwrap()
            .contains("Warnings:")
    );

    mock.assert_async().await;
}
