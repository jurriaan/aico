mod common;
use crate::common::load_view;
use assert_cmd::cargo::cargo_bin_cmd;
use common::init_session_with_history;
use mockito::{Matcher, Server};
use predicates::prelude::*;
use serde_json::json;
use std::fs;
use tempfile::tempdir;

fn setup_session(root: &std::path::Path) {
    // Initialize a session
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();
}

#[tokio::test]
async fn test_ask_command_injects_alignment_and_streams_response() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    // GIVEN a file in context to trigger alignment prompts
    let file_path = root.join("main.py");
    // Write without trailing newline to match expected_context_block exactly
    fs::write(&file_path, "print('hello')").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "main.py"])
        .assert()
        .success();

    // AND a mock OpenAI server
    let mut server = Server::new_async().await;
    let mock_url = server.url();

    // Prepare streaming response chunks
    let chunk1 = json!({
        "choices": [{"delta": {"content": "Hello "}, "index": 0, "finish_reason": null}]
    });
    let chunk2 = json!({
        "choices": [{"delta": {"content": "World"}, "index": 0, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    });

    let sys_prompt = aico::consts::DEFAULT_SYSTEM_PROMPT;
    let expected_context_block =
        "<context>\n  <file path=\"main.py\">\nprint('hello')\n  </file>\n</context>";
    let expected_context_intro = format!(
        "{}\n\n{}",
        aico::consts::STATIC_CONTEXT_INTRO,
        expected_context_block
    );

    let expected_body = json!({
        "model": "test-model",
        "messages": [
            {
                "role": "system",
                "content": sys_prompt
            },
            {
                "role": "user",
                "content": expected_context_intro
            },
            {
                "role": "assistant",
                "content": aico::consts::STATIC_CONTEXT_ANCHOR
            },
            {
                "role": "user",
                "content": aico::consts::ALIGNMENT_CONVERSATION_USER
            },
            {
                "role": "assistant",
                "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT
            },
            {
                "role": "user",
                "content": "Explain this code"
            }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    // Mock the chat completion endpoint with exact JSON matching
    let mock = server
        .mock("POST", "/chat/completions")
        .match_header("Authorization", "Bearer sk-test")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: {}\n\ndata: [DONE]\n\n",
            chunk1, chunk2
        ))
        .create_async()
        .await;

    // WHEN running `aico ask`
    let mut cmd = cargo_bin_cmd!("aico");
    cmd.current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", mock_url) // Point to mock server
        .args(["ask", "Explain this code"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Hello World"));

    mock.assert_async().await;

    // VERIFY: Session history updated
}

#[tokio::test]
async fn test_model_flag_does_not_persist_to_session_view() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root); // Initially set to openai/test-model

    let mut server = Server::new_async().await;
    let _mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: [DONE]\n\n")
        .create_async()
        .await;

    // Run ask with an override
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "--model", "openai/ephemeral-override", "hello"])
        .assert()
        .success();

    // VERIFY: The session view file still contains the original model
    let view_path = root.join(".aico/sessions/main.json");
    let view_content = fs::read_to_string(view_path).unwrap();
    assert!(view_content.contains("openai/test-model"));
    assert!(!view_content.contains("openai/ephemeral-override"));

    // Indices should be [0, 1] (user, asst)
    assert!(view_content.contains("\"message_indices\":[0,1]"));

    // Check store content: verify the last two records correspond to our override turn
    let history_path = root.join(".aico/history/0.jsonl");
    let history_content = fs::read_to_string(history_path).unwrap();
    let lines: Vec<&str> = history_content.lines().collect();

    let last_asst = lines
        .iter()
        .rev()
        .find(|l| l.contains("\"role\":\"assistant\""))
        .unwrap();
    let last_user = lines
        .iter()
        .rev()
        .find(|l| l.contains("\"role\":\"user\""))
        .unwrap();

    assert!(last_user.contains("hello"));
    assert!(last_asst.contains("\"model\":\"openai/ephemeral-override\""));
}

#[tokio::test]
async fn test_prompt_fails_with_no_input() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    // WHEN running aico ask/gen/prompt with no args and no stdin
    // assert_cmd doesn't attach TTY by default
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("ask")
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Error: Invalid input: Prompt is required.",
        ));
}

#[tokio::test]
async fn test_prompt_model_flag_overrides_session_default() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::PartialJson(json!({
            "model": "gpt-4-override",
            "stream": true
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
        .args(["ask", "--model", "openai/gpt-4-override", "hello"])
        .assert()
        .success();

    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_input_scenarios_stdin() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // Expected body when reading from stdin with no context
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            { "role": "user", "content": "stdin prompt" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: {}\n\ndata: [DONE]\n\n") // Empty valid response
        .create_async()
        .await;

    // WHEN running `aico ask` with piped input
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .arg("ask")
        .write_stdin("stdin prompt")
        .assert()
        .success();

    mock.assert_async().await;
}

#[tokio::test]
async fn test_ask_command_with_diff_response_saves_derived_content() {
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

    // AI responds with a diff even though we are in Conversation mode
    let llm_diff_response = "File: app.py\n<<<<<<< SEARCH\ndef main(): pass\n=======\ndef main(): print('hello')\n>>>>>>> REPLACE";

    let chunk = json!({
        "choices": [{"delta": {"content": llm_diff_response}, "index": 0}],
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    // WHEN running 'ask' in a non-tty environment (capture clean output)
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "change main"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    // THEN the clean diff is printed to stdout (Flexible Contract parity)
    let stdout_str = String::from_utf8(output).unwrap();
    assert!(stdout_str.contains("--- a/app.py"));
    assert!(stdout_str.contains("+def main(): print('hello')"));

    mock.assert_async().await;

    // AND derived content is saved in the history store
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"unified_diff\":\"--- a/app.py"));
    // The "type" tag is serialized by serde(tag = "type") as defined in models.rs
    assert!(content.contains("\"type\":\"diff\""));
}

#[tokio::test]
async fn test_prompt_no_history_flag_omits_history_from_llm_call() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let mock_url = server.url();

    // 1. Create initial history
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
        .env("OPENAI_BASE_URL", &mock_url)
        .args(["ask", "initial prompt"])
        .assert()
        .success();

    mock1.assert_async().await;

    // 2. Run with --no-history. Expected body should NOT have the first response.
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            { "role": "user", "content": "no-history prompt" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock2 = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body("data: {\"choices\":[{\"delta\":{\"content\":\"resp 2\"}}]}\n\ndata: [DONE]\n\n")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", &mock_url)
        .args(["ask", "--no-history", "no-history prompt"])
        .assert()
        .success();

    mock2.assert_async().await;

    // Verify history still has both pairs locally
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("initial prompt"));
    assert!(content.contains("no-history prompt"));
}

#[tokio::test]
async fn test_prompt_passthrough_mode_bypasses_context_and_formatting() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    // GIVEN a file in context
    let file_path = root.join("file.py");
    fs::write(&file_path, "some context").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file.py"])
        .assert()
        .success();

    let mut server = Server::new_async().await;
    let mock_url = server.url();

    // AND we expect a body that has NO context blocks and NO XML wrapping
    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": "raw prompt text" }
        ],
        "stream": true,
        "stream_options": { "include_usage": true }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .match_body(Matcher::Json(expected_body))
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(
            "data: {\"choices\":[{\"delta\":{\"content\":\"raw response\"}}]}\n\ndata: [DONE]\n\n",
        )
        .create_async()
        .await;

    // WHEN running `aico ask --passthrough`
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", mock_url)
        .args(["ask", "--passthrough", "raw prompt text"])
        .assert()
        .success()
        .stdout(predicate::str::contains("raw response"));

    mock.assert_async().await;

    // VERIFY: history reflects passthrough
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"passthrough\":true"));
}

#[tokio::test]
async fn test_prompt_input_scenarios_both_cli_and_piped() {
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

    // Verify history saved both
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"content\":\"cli arg\""));
    assert!(content.contains("\"piped_content\":\"pipe in\""));
}

#[tokio::test]
async fn test_prompt_with_history_reconstructs_piped_content_correctly() {
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
async fn test_ask_displays_token_usage_with_k_formatting_and_details() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // Mock response with high token counts and details
    let chunk = json!({
        "choices": [{"delta": {"content": "Response"}, "index": 0}],
        "usage": {
            "prompt_tokens": 54467,
            "completion_tokens": 814,
            "total_tokens": 55281,
            "cached_tokens": 10200,
            "reasoning_tokens": 200
        }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "big prompt"])
        .assert()
        .success()
        .stderr(predicate::str::contains(
            "Tokens: 54.5k (10.2k cached) sent, 814 (200 reasoning) received.",
        ));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_ask_piped_output_falls_back_to_raw_content() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let llm_response = "This is a simple answer without any code.";
    let chunk = json!({
        "choices": [{"delta": {"content": llm_response}, "index": 0}],
    });

    let _mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    // WHEN running ask piped
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "What is 2+2?"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    // THEN stdout contains the raw content (Flexible Contract)
    assert_eq!(String::from_utf8(output).unwrap(), llm_response);
}

#[tokio::test]
async fn test_ask_fails_gracefully_on_api_error() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;
    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(401)
        .with_body("Invalid API Key")
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-wrong")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "hello"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "API Error (Status: 401 Unauthorized): Invalid API Key",
        ));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_prompt_with_excluded_history_omits_messages() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 3 pairs
    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    init_session_with_history(
        root,
        vec![
            ("prompt 1", "response 1"),
            ("prompt 2", "response 2"),
            ("prompt 3", "response 3"),
        ],
    );

    // Ensure model has a prefix
    let view_path = root.join(".aico/sessions/main.json");
    let mut view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(&view_path).unwrap()).unwrap();
    view.model = "openai/test-model".to_string();
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // AND we exclude pair index 1
    let mut view = load_view(root);
    view.excluded_pairs = vec![1];
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // AND a mock server
    let mut server = Server::new_async().await;
    let mock_url = server.url();

    let expected_body = json!({
        "model": "test-model",
        "messages": [
            { "role": "system", "content": aico::consts::DEFAULT_SYSTEM_PROMPT },
            { "role": "user", "content": "prompt 1" },
            { "role": "assistant", "content": "response 1" },
            // prompt 2 / response 2 should be missing
            { "role": "user", "content": "prompt 3" },
            { "role": "assistant", "content": "response 3" },
            { "role": "user", "content": aico::consts::ALIGNMENT_CONVERSATION_USER },
            { "role": "assistant", "content": aico::consts::ALIGNMENT_CONVERSATION_ASSISTANT },
            { "role": "user", "content": "prompt 4" }
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

    // WHEN running `aico ask`
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", mock_url)
        .args(["ask", "prompt 4"])
        .assert()
        .success();

    mock.assert_async().await;
}

#[test]
fn test_ask_recovers_from_stream_interruption() {
    use std::io::{BufRead, BufReader, Write};
    use std::net::{Shutdown, TcpListener};
    use std::thread;
    use std::time::Duration;

    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    // 1. Bind a standard synchronous TCP listener
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let mock_url = format!("http://127.0.0.1:{}", port);

    // 2. Spawn server in a background thread
    thread::spawn(move || {
        // Accept the connection from 'aico'
        let (mut stream, _) = listener.accept().unwrap();
        let mut reader = BufReader::new(stream.try_clone().unwrap());

        // Drain headers (naive loop is fine for test)
        let mut line = String::new();
        while let Ok(n) = reader.read_line(&mut line) {
            if n == 0 || line == "\r\n" {
                break;
            }
            line.clear();
        }

        // Send Headers
        // Note: Transfer-Encoding: chunked is key here
        let response_headers = "HTTP/1.1 200 OK\r\n\
                                Content-Type: text/event-stream\r\n\
                                Transfer-Encoding: chunked\r\n\r\n";
        stream.write_all(response_headers.as_bytes()).unwrap();

        // Send ONE valid chunk containing partial JSON
        // Format: <HexLength>\r\n<Data>\r\n
        let json_payload =
            "data: {\"choices\": [{\"delta\": {\"content\": \"This is a partial \"}}]}\n\n";
        let chunk = format!("{:x}\r\n{}\r\n", json_payload.len(), json_payload);
        stream.write_all(chunk.as_bytes()).unwrap();
        stream.flush().unwrap();

        // CRITICAL: Sleep briefly to ensure 'aico' (reqwest) actually reads the bytes
        // from the OS buffer before we kill the connection.
        thread::sleep(Duration::from_millis(10));

        // Hard Kill: Shutdown Both to force a TCP FIN/RST.
        // We purposefully DO NOT send the "0\r\n\r\n" terminating chunk.
        // This forces reqwest to throw "error decoding response body" / "premature EOF".
        let _ = stream.shutdown(Shutdown::Both);
    });

    // 3. Run aico
    // It should succeed (exit 0) because we implemented partial recovery
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", mock_url)
        .args(["ask", "trigger error"])
        .assert()
        .success()
        // Verify we caught the error and printed a warning
        .stderr(predicate::str::contains("[WARN] Stream interrupted:"))
        // Verify we printed what we received so far
        .stdout(predicate::str::contains("This is a partial "));

    // 4. Verify Persistence
    // The partial message should be saved in the history file
    let history_path = root.join(".aico/history/0.jsonl");
    let history_content = fs::read_to_string(history_path).expect("History file not created");

    let assistant_record = history_content
        .lines()
        .find(|l| l.contains("\"role\":\"assistant\""))
        .expect("Assistant record missing from history");

    assert!(assistant_record.contains("This is a partial "));
}

#[tokio::test]
async fn test_calculate_cost_prioritizes_api_reported_cost() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // GIVEN an API response with a specific cost field
    let chunk = json!({
        "choices": [{"delta": {"content": "Response"}, "index": 0}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost": 0.999
        }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk))
        .create_async()
        .await;

    // WHEN running aico ask
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "test cost priority"])
        .assert()
        .success()
        .stderr(predicate::str::contains("Cost: $1.00"));

    mock.assert_async().await;

    // THEN verify the exact cost is preserved in the history store
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("\"cost\":0.999"));
}

#[tokio::test]
async fn test_ask_merges_fragmented_display_items_in_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // GIVEN a fragmented response from the LLM
    let chunk1 = json!({ "choices": [{"delta": {"content": "I am "}, "index": 0}] });
    let chunk2 = json!({ "choices": [{"delta": {"content": "split "}, "index": 0}] });
    let chunk3 = json!({ "choices": [{"delta": {"content": "across chunks."}, "index": 0}] });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!(
            "data: {}\n\ndata: {}\n\ndata: {}\n\ndata: [DONE]\n\n",
            chunk1, chunk2, chunk3
        ))
        .create_async()
        .await;

    // WHEN running ask
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "fragmentation test"])
        .assert()
        .success();

    mock.assert_async().await;

    // THEN verify the history store has merged the items into a single Markdown block
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();

    let asst_msg: serde_json::Value = content
        .lines()
        .find(|l| l.contains("\"role\":\"assistant\""))
        .and_then(|l| serde_json::from_str(l).ok())
        .expect("Assistant message should be in history");

    let display_items = asst_msg["derived"]["display_content"]
        .as_array()
        .expect("display_content should be an array");

    assert_eq!(
        display_items.len(),
        1,
        "Display items should be merged. Got: {:?}",
        display_items
    );
    assert_eq!(display_items[0]["type"], "markdown");
    assert_eq!(display_items[0]["content"], "I am split across chunks.");
}
