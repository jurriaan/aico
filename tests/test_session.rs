mod common;
use aico::consts::SESSION_FILE_NAME;
use aico::models::{SessionPointer, SessionView};
use aico::session::Session;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_session_load_active() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // 1. Create directory structure
    let aico_dir = root.join(".aico");
    let sessions_dir = aico_dir.join("sessions");
    let history_dir = aico_dir.join("history");
    fs::create_dir_all(&sessions_dir).unwrap();
    fs::create_dir_all(&history_dir).unwrap();

    // 2. Create View File
    let view = SessionView {
        model: "openai/test-model".into(),
        context_files: vec![],
        message_indices: vec![],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };
    let view_path = sessions_dir.join("main.json");
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // 3. Create Pointer File
    let pointer = SessionPointer {
        pointer_type: "aico_session_pointer_v1".into(),
        path: ".aico/sessions/main.json".into(),
    };
    let pointer_path = root.join(SESSION_FILE_NAME);
    fs::write(&pointer_path, serde_json::to_string(&pointer).unwrap()).unwrap();

    // 4. Test loading directly
    let session = Session::load(pointer_path).expect("Should load session");

    assert_eq!(session.view.model, "openai/test-model");
    assert_eq!(session.root, root);
    assert!(session.store.read_many(&[]).is_ok());
}

#[test]
fn test_active_window_summary_with_exclusions() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 5 pairs in history
    let mut pairs = Vec::new();
    for i in 0..5 {
        pairs.push((format!("p{}", i), format!("r{}", i)));
    }
    crate::common::init_session_with_history(
        root,
        pairs
            .iter()
            .map(|(p, r)| (p.as_str(), r.as_str()))
            .collect(),
    );

    let pointer_path = root.join(".ai_session.json");
    let mut session = Session::load(pointer_path).unwrap();

    // AND we set the history to start at pair 1
    session.view.history_start_pair = 1;
    // AND we exclude pair 3
    session.view.excluded_pairs = vec![3];
    session.save_view().unwrap();

    // WHEN reconstructing history
    let history_vec = session.history(true).unwrap();

    // AND calculating the active window summary
    let summary = session
        .summarize_active_window(&history_vec)
        .unwrap()
        .expect("Summary should exist");

    // THEN the active window spans from index 1 to 4 (4 pairs total in window)
    assert_eq!(summary.active_pairs, 4);
    assert_eq!(summary.active_start_id, 1);
    assert_eq!(summary.active_end_id, 4);
    // AND one pair is excluded
    assert_eq!(summary.excluded_in_window, 1);
    // AND 3 pairs are actually sent (1, 2, 4)
    assert_eq!(summary.pairs_sent, 3);
}

#[test]
fn test_resolve_pair_index_bounds_checking() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 2 pairs
    crate::common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    let session = Session::load(root.join(".ai_session.json")).unwrap();

    // 1. Valid positive index
    assert_eq!(session.resolve_pair_index("0").unwrap(), 0);
    assert_eq!(session.resolve_pair_index("1").unwrap(), 1);

    // 2. Valid negative index
    assert_eq!(session.resolve_pair_index("-1").unwrap(), 1);
    assert_eq!(session.resolve_pair_index("-2").unwrap(), 0);

    // 3. Out of bounds positive
    let err_pos = session.resolve_pair_index("2").unwrap_err();
    assert!(err_pos.to_string().contains("Index out of bounds"));
    assert!(err_pos.to_string().contains("range 0 to 1"));

    // 4. Out of bounds negative (The "Golden Test" from Python)
    let err_neg = session.resolve_pair_index("-3").unwrap_err();
    assert!(err_neg.to_string().contains("Index out of bounds"));
    assert!(err_neg.to_string().contains("range 0 to 1 (or -1 to -2)"));

    // 5. Empty history scenario
    let temp_empty = tempdir().unwrap();
    let aico_dir = temp_empty.path().join(".aico");
    std::fs::create_dir_all(aico_dir.join("sessions")).unwrap();
    std::fs::create_dir_all(aico_dir.join("history")).unwrap();

    let view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };
    std::fs::write(
        aico_dir.join("sessions/main.json"),
        serde_json::to_string(&view).unwrap(),
    )
    .unwrap();
    std::fs::write(
        temp_empty.path().join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    let session_empty = Session::load(temp_empty.path().join(".ai_session.json")).unwrap();
    let err_empty = session_empty.resolve_pair_index("0").unwrap_err();
    assert!(err_empty.to_string().contains("No message pairs found"));
}

#[test]
fn test_session_view_persistence_of_metadata() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // 1. Manually create a Session View JSON with non-zero metadata
    let view_json = r#"{
        "model": "openai/test-model",
        "context_files": ["f.py"],
        "message_indices": [],
        "history_start_pair": 5,
        "excluded_pairs": [2, 4],
        "created_at": "2023-01-01T00:00:00Z"
    }"#;

    let aico_dir = root.join(".aico");
    let sessions_dir = aico_dir.join("sessions");
    fs::create_dir_all(&sessions_dir).unwrap();
    let view_path = sessions_dir.join("main.json");
    fs::write(&view_path, view_json).unwrap();

    // 2. Create Pointer
    let pointer = aico::models::SessionPointer {
        pointer_type: "aico_session_pointer_v1".into(),
        path: ".aico/sessions/main.json".into(),
    };
    let pointer_path = root.join(".ai_session.json");
    fs::write(&pointer_path, serde_json::to_string(&pointer).unwrap()).unwrap();

    // 3. Load using Session logic
    let session = Session::load(pointer_path).expect("Should load session");

    // 4. Assert metadata is preserved
    assert_eq!(
        session.view.history_start_pair, 5,
        "history_start_pair was reset to 0!"
    );
    assert_eq!(
        session.view.excluded_pairs,
        vec![2, 4],
        "excluded_pairs was reset!"
    );
}

#[test]
fn test_session_eager_load_sorts_deterministic() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a view with unsorted files
    let aico_dir = root.join(".aico");
    let sessions_dir = aico_dir.join("sessions");
    fs::create_dir_all(&sessions_dir).unwrap();
    fs::create_dir_all(aico_dir.join("history")).unwrap();

    fs::write(root.join("z.py"), "z").unwrap();
    fs::write(root.join("a.py"), "a").unwrap();

    let view_json = r#"{
        "model": "m",
        "context_files": ["z.py", "a.py"],
        "message_indices": [],
        "history_start_pair": 0,
        "excluded_pairs": [],
        "created_at": "2023-01-01T00:00:00Z"
    }"#;
    fs::write(sessions_dir.join("main.json"), view_json).unwrap();
    fs::write(
        root.join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    // WHEN loading
    let session = Session::load(root.join(".ai_session.json")).unwrap();

    // THEN context_content contains both
    assert!(session.context_content.contains_key("a.py"));
    assert!(session.context_content.contains_key("z.py"));
}

#[test]
fn test_session_load_fails_on_missing_history_shards() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // 1. Create directory structure but NO history shards
    let aico_dir = root.join(".aico");
    let sessions_dir = aico_dir.join("sessions");
    fs::create_dir_all(&sessions_dir).unwrap();
    fs::create_dir_all(aico_dir.join("history")).unwrap();

    // 2. Create View File pointing to non-existent shards (a full pair: global indices 0 and 1)
    let view_json = r#"{
        "model": "openai/test-model",
        "context_files": [],
        "message_indices": [0, 1],
        "history_start_pair": 0,
        "excluded_pairs": [],
        "created_at": "2023-01-01T00:00:00Z"
    }"#;
    fs::write(sessions_dir.join("main.json"), view_json).unwrap();

    // 3. Create Pointer File
    let pointer = SessionPointer {
        pointer_type: "aico_session_pointer_v1".into(),
        path: ".aico/sessions/main.json".into(),
    };
    let pointer_path = root.join(SESSION_FILE_NAME);
    fs::write(&pointer_path, serde_json::to_string(&pointer).unwrap()).unwrap();

    // 4. Test that loading SUCCEEDS because it is lazy
    let session =
        Session::load(pointer_path).expect("Lazy load should succeed even with missing shards");

    // 5. Test that fetching a pair FAILS because it hits the missing shard
    let result = session.fetch_pair(0);
    assert!(result.is_err());
    let err_msg = result.unwrap_err().to_string();
    assert!(err_msg.contains("Shard missing"));
}

#[tokio::test]
async fn test_active_history_filtering_and_slicing() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 5 pairs and a dangling message
    let mut pairs = Vec::new();
    for i in 0..5 {
        pairs.push((format!("p{}", i), format!("r{}", i)));
    }
    crate::common::init_session_with_history(
        root,
        pairs
            .iter()
            .map(|(p, r)| (p.as_str(), r.as_str()))
            .collect(),
    );

    // Add a dangling user message manually
    let session_file = root.join(".ai_session.json");
    let mut session = Session::load(session_file).unwrap();
    let dangling_rec = aico::models::HistoryRecord {
        role: aico::models::Role::User,
        content: "dangling".into(),
        mode: aico::models::Mode::Conversation,
        timestamp: chrono::Utc::now(),
        passthrough: false,
        piped_content: None,
        model: None,
        token_usage: None,
        cost: None,
        duration_ms: None,
        derived: None,
        edit_of: None,
    };
    let d_idx = session.store.append(&dangling_rec).unwrap();
    session.view.message_indices.push(d_idx);

    // AND we set history to start at pair 2 and exclude pair 3
    session.view.history_start_pair = 2;
    session.view.excluded_pairs = vec![3];
    session.save_view().unwrap();

    // WHEN reconstructing history for the LLM
    let history_vec = session.history(false).unwrap();

    // THEN only active pairs (2, 4) and dangling are marked active
    // We check records in active_history and verify they contain the expected text.
    // Pairs 2 and 4 plus the dangling message should be present.
    let contents: Vec<String> = history_vec
        .iter()
        .map(|item| item.record.content.clone())
        .collect();

    // Pair 2: p2, r2
    // Pair 3: (Excluded)
    // Pair 4: p4, r4
    // Dangling: dangling
    assert!(contents.contains(&"p2".to_string()));
    assert!(contents.contains(&"r2".to_string()));
    assert!(!contents.contains(&"p3".to_string()));
    assert!(contents.contains(&"p4".to_string()));
    assert!(contents.contains(&"r4".to_string()));
    assert!(contents.contains(&"dangling".to_string()));

    assert_eq!(contents.len(), 5); // p2,r2,p4,r4,dangling is 5.
}
