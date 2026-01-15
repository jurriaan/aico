mod common;
use crate::common::setup_session;
use aico::llm::api_models::{ChunkDelta, ReasoningDetail};
use aico::llm::executor::{append_reasoning_delta, extract_reasoning_header};
use assert_cmd::cargo::cargo_bin_cmd;
use mockito::Server;

#[test]
fn test_reasoning_extraction_consolidated() {
    let cases = vec![
        // Basic Markdown - Requires newline to be stable during streaming
        ("### Planning\n", Some("Planning")),
        // Bold headers - Stable because they require closing **
        ("**Analysis**", Some("Analysis")),
        // Last match wins
        (
            "## Step 1\n### Step 2\n**Final Thought**",
            Some("Final Thought"),
        ),
        // PREVENT FLICKER: Partial Markdown header without newline should return None
        ("### Evalu", None),
        // SPACING
        ("####   Spaced Header   \n", Some("Spaced Header")),
        ("**  Spaced Bold  **", Some("Spaced Bold")),
        // UNICODE
        ("### ✨ Brillant\n", Some("✨ Brillant")),
        // MALFORMED
        ("Just text", None),
        ("#### ", None),
        ("**Unclosed", None),
    ];

    for (input, expected) in cases {
        let result = extract_reasoning_header(input);
        assert_eq!(result.as_deref(), expected, "Failed on input: {:?}", input);
    }
}

#[test]
fn test_extract_reasoning_header_incremental_bold() {
    let chunks = vec![
        "**Ref",
        "ining",
        " Markdown",
        " Header",
        " Processing",
        "**\n\nI",
    ];

    let mut buffer = String::new();

    // Step 1: "**Ref" -> Should be None (waiting for closing **)
    buffer.push_str(chunks[0]);
    assert_eq!(
        extract_reasoning_header(&buffer),
        None,
        "Partial bold header matched prematurely: '{}'",
        buffer
    );

    // Step 2-5: Accumulating -> Should still be None
    for i in 1..5 {
        buffer.push_str(chunks[i]);
        assert_eq!(
            extract_reasoning_header(&buffer),
            None,
            "Partial bold header matched prematurely at chunk {}: '{}'",
            i,
            buffer
        );
    }

    // Step 6: Closing "**" -> Should Match Full String
    buffer.push_str(chunks[5]);
    assert_eq!(
        extract_reasoning_header(&buffer),
        Some("Refining Markdown Header Processing"),
        "Failed to match complete bold header"
    );
}

#[test]
fn test_reasoning_double_accumulation_regression() {
    // Regression test: Ensure we don't double-accumulate if a provider sends
    // both direct reasoning content and structured reasoning details.
    let chunk_json = serde_json::json!({
        "choices": [{
            "delta": {
                "reasoning_content": "**Analy",
                "reasoning_details": [{
                    "type": "reasoning.text",
                    "text": "**Analy"
                }]
            }
        }]
    });

    let parsed: aico::llm::api_models::ChatCompletionChunk =
        serde_json::from_value(chunk_json).unwrap();
    let choice = &parsed.choices[0];

    let mut reasoning_delta = String::new();
    append_reasoning_delta(&mut reasoning_delta, &choice.delta);

    let header = extract_reasoning_header(&reasoning_delta);

    assert_eq!(header, None, "Double accumulation detected: {:?}", header);
}

#[test]
fn test_reasoning_fallback_when_content_is_present_but_empty() {
    let delta = ChunkDelta {
        content: None,
        reasoning_content: Some("".to_string()),
        reasoning_details: Some(vec![ReasoningDetail::Text {
            text: "### Real Plan\n".to_string(),
        }]),
    };

    let mut result = String::new();
    append_reasoning_delta(&mut result, &delta);
    assert_eq!(extract_reasoning_header(&result), Some("Real Plan"));
}

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
