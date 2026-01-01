mod common;
use crate::common::setup_session;
use assert_cmd::cargo::cargo_bin_cmd;
use mockito::Server;

#[tokio::test]
async fn test_reasoning_to_content_transition_ui() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    let mut server = Server::new_async().await;

    // Test various reasoning field aliases and content transition.
    let chunks = vec![
        "data: {\"choices\":[{\"delta\":{\"reasoning_details\":[{\"type\":\"reasoning.text\",\"text\":\"Analyzing...\"}]}}]}",
        "data: {\"choices\":[{\"delta\":{\"reasoning\":\"### Planning\\n1. Search for bugs\\n2. Fix them\"}}]}",
        "data: {\"choices\":[{\"delta\":{\"content\":\"Found a bug.\"}}]}",
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
        .args([
            "ask",
            "--model",
            "openai/o1+reasoning_effort=low",
            "find bugs",
        ])
        .assert()
        .success();

    let stdout = String::from_utf8(assert.get_output().stdout.clone()).unwrap();
    assert!(stdout.contains("Found a bug."));
    mock.assert_async().await;
}
