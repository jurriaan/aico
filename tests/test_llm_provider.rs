mod common;
use crate::common::setup_session;
use aico::llm::executor::extract_reasoning_header;
use assert_cmd::cargo::cargo_bin_cmd;
use mockito::Server;
use serde_json::json;

#[test]
fn test_extract_reasoning_header() {
    // Basic Markdown
    assert_eq!(
        extract_reasoning_header("### Planning\nI will start by..."),
        Some("Planning".into())
    );
    // Bold
    assert_eq!(
        extract_reasoning_header("**Thought Process**\nFirst..."),
        Some("Thought Process".into())
    );
    // Last match wins
    assert_eq!(
        extract_reasoning_header("## One\n**Two**"),
        Some("Two".into())
    );
    // No match
    assert_eq!(extract_reasoning_header("Just some text"), None);
}

#[tokio::test]
async fn test_handle_unified_streaming_openai() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // Simulate multiple chunks to verify reconstruction
    let chunks = vec![
        r#"data: {"choices":[{"delta":{"role":"assistant","content":"Hel"}}]}"#,
        r#"data: {"choices":[{"delta":{"content":"lo "}}]}"#,
        r#"data: {"choices":[{"delta":{"content":"world"}}]}"#,
        "data: [DONE]",
    ];

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(chunks.join("\n\n") + "\n\n")
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "hi"])
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();
    assert_eq!(stdout.trim(), "Hello world");
    mock.assert_async().await;
}

#[tokio::test]
async fn test_openai_provider_process_chunk_with_usage() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    let chunk_with_usage = json!({
        "choices": [],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15
        }
    });

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(format!("data: {}\n\ndata: [DONE]\n\n", chunk_with_usage))
        .create_async()
        .await;

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "token test"])
        .assert()
        .success();

    // Verify history reflects usage
    let history_path = root.join(".aico/history/0.jsonl");
    let content = std::fs::read_to_string(history_path).unwrap();
    assert!(content.contains(r#""prompt_tokens":10"#));
    assert!(content.contains(r#""completion_tokens":5"#));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_handle_unified_streaming_openrouter() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // OpenRouter often forwards extra fields or usage in middle chunks
    let chunks = vec![
        r#"data: {"choices":[{"delta":{"content":"OR "}}], "usage": null}"#,
        r#"data: {"choices":[{"delta":{"content":"Response"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}"#,
        "data: [DONE]",
    ];

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(chunks.join("\n\n") + "\n\n")
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENROUTER_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "--model", "openrouter/meta-llama/llama-3", "test"])
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8(output.stdout.clone()).unwrap();
    assert!(stdout.contains("OR Response"));

    // Verify history usage
    let history_path = root.join(".aico/history/0.jsonl");
    let content = std::fs::read_to_string(history_path).unwrap();
    assert!(content.contains(r#""total_tokens":150"#));

    mock.assert_async().await;
}

#[tokio::test]
async fn test_handle_fragmented_sse_stream() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    crate::common::setup_session(root);

    let mut server = Server::new_async().await;

    // Simulate fragmented SSE chunks that split mid-line and mid-JSON
    let fragmented_chunks = vec![
        "da",
        "ta: {\"choices\":[{\"delta\":{\"content\":\"Frag",
        "ment\"}}]}\n",
        "\ndata: {\"choices\":[{\"delta\":{\"content\":\"ed\"}}]}\n\ndata: [DONE]\n\n",
    ];

    let mock = server
        .mock("POST", "/chat/completions")
        .with_status(200)
        .with_header("content-type", "text/event-stream")
        .with_body(fragmented_chunks.join(""))
        .create_async()
        .await;

    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("OPENAI_API_KEY", "sk-test")
        .env("OPENAI_BASE_URL", server.url())
        .args(["ask", "test fragmentation"])
        .assert()
        .success();

    let stdout = String::from_utf8(assert.get_output().stdout.clone()).unwrap();
    assert_eq!(stdout.trim(), "Fragmented");
    mock.assert_async().await;
}

#[tokio::test]
async fn test_openai_provider_process_chunk_reasoning() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // Simulate thinking/reasoning header extraction from content stream
    let reasoning_content = "### Reasoning\nChecking logic...\n\nHello!";
    let chunk = json!({
        "choices": [{"delta": {"content": reasoning_content}}]
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
        .args(["ask", "reason test"])
        .assert()
        .success();

    mock.assert_async().await;
}
