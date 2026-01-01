mod common;
use aico::llm::executor::build_request;
use aico::models::Mode;
use common::init_session_with_history;
use tempfile::tempdir;

#[tokio::test]
async fn test_active_window_respects_start_pair() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 3 pairs
    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    let pointer_path = root.join(".ai_session.json");
    let mut session = aico::session::Session::load(pointer_path).unwrap();

    // Force model prefix for LlmClient
    session.view.model = "openai/test-model".to_string();

    // AND we set the history to start at pair 2 (only the last pair should be active)
    session.view.history_start_pair = 2;
    session.save_view().unwrap();

    // Re-load session to ensure the history window is re-populated with the new start pair
    let session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    // WHEN we build a request
    let req = build_request(
        &session,
        "System",
        "Prompt",
        Mode::Conversation,
        false,
        false,
    )
    .await
    .unwrap();

    // THEN the messages should NOT contain p0, r0, p1, or r1
    let contents: Vec<String> = req.messages.iter().map(|m| m.content.clone()).collect();

    // Static context blocks and alignment will be there, but let's check for the history messages
    assert!(!contents.contains(&"p0".to_string()));
    assert!(!contents.contains(&"r0".to_string()));
    assert!(!contents.contains(&"p1".to_string()));
    assert!(!contents.contains(&"r1".to_string()));

    // p2 and r2 SHOULD be there
    assert!(contents.contains(&"p2".to_string()));
    assert!(contents.contains(&"r2".to_string()));
}
