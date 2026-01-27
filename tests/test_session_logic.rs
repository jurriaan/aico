mod common;
use aico::session::Session;
use assert_cmd::cargo::cargo_bin_cmd;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_expand_index_ranges() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    // 5 pairs total (indices 0 to 4)
    crate::common::init_session_with_history(
        root,
        vec![
            ("p0", "r0"),
            ("p1", "r1"),
            ("p2", "r2"),
            ("p3", "r3"),
            ("p4", "r4"),
        ],
    );

    // 1. Simple Inclusive Range
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "1..3"])
        .assert()
        .success();
    let view = crate::common::load_view(root);
    assert_eq!(view.excluded_pairs, vec![1, 2, 3]);

    // Cleanup for next sub-test
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0..4"])
        .assert()
        .success();

    // 2. Reverse Range
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "3..1"])
        .assert()
        .success();
    let view = crate::common::load_view(root);
    assert_eq!(view.excluded_pairs, vec![1, 2, 3]);

    // 3. Negative Range (-3 is index 2, -1 is index 4)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0..4"])
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "-3..-1"])
        .assert()
        .success();
    let view = crate::common::load_view(root);
    assert_eq!(view.excluded_pairs, vec![2, 3, 4]);
}

#[test]
fn test_undo_range_logic_reverse_and_redundant() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    crate::common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    // Reverse range 2..0 should be same as 0..2
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "2..0", "1"])
        .assert()
        .success();

    let view = crate::common::load_view(root);
    assert_eq!(view.excluded_pairs, vec![0, 1, 2]);
}

#[test]
fn test_mixed_sign_range_safety_catch() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    crate::common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Python parity: mixed sign ranges like 0..-1 are literal and fail
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0..-1"])
        .assert()
        .failure()
        .stderr(predicates::str::contains("Invalid index '0..-1'"));
}

#[test]
fn test_active_message_indices_shared_history_signal() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    crate::common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    let session = Session::load(root.join(".ai_session.json")).unwrap();
    // A session with 2 pairs has 4 message indices
    assert_eq!(session.view.message_indices.len(), 4);

    // Pair 0 is (global 0, global 1), Pair 1 is (global 2, global 3)
    let (_, _, u_id0, a_id0) = session.fetch_pair(0).unwrap();
    assert_eq!(u_id0, 0);
    assert_eq!(a_id0, 1);

    let (_, _, u_id1, a_id1) = session.fetch_pair(1).unwrap();
    assert_eq!(u_id1, 2);
    assert_eq!(a_id1, 3);

    // Verify resolve_pair_index parity with 0-based and -1 based
    assert_eq!(session.resolve_pair_index("0").unwrap(), 0);
    assert_eq!(session.resolve_pair_index("-1").unwrap(), 1);
}

#[test]
fn test_get_active_history_filters_and_slices() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 4 pairs (Indices 0, 1, 2, 3) and a dangling message
    let pairs = vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2"), ("p3", "r3")];
    crate::common::init_session_with_history(root, pairs);

    let session_file = root.join(".ai_session.json");
    let mut session = Session::load(session_file).unwrap();

    // Manually add a dangling user message
    let dangling_rec = aico::models::HistoryRecord {
        role: aico::models::Role::User,
        content: "dangling user".into(),
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

    // AND we configure the window: Start at pair 1, exclude pair 2
    session.view.history_start_pair = 1;
    session.view.excluded_pairs = vec![2];
    session.save_view().unwrap();

    // WHEN reconstructing history for the LLM
    let history_vec = session.history(false).unwrap();

    // THEN only messages from active pairs and dangling user are present in active_history
    let contents: Vec<String> = history_vec
        .iter()
        .map(|h| h.record.content.clone())
        .collect();

    // indices in view are [0, 1, 2, 3, 4, 5, 6, 7, 8]
    // history_start_pair = 1 (start at index 2)
    // excluded_pairs = [2] (exclude indices 4, 5)
    // active indices: [2, 3, 6, 7, 8]
    // active contents: [p1, r1, p3, r3, dangling user]

    assert_eq!(contents, vec!["p1", "r1", "p3", "r3", "dangling user"]);
}

#[test]
fn test_context_files_update_via_add_persistence() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    crate::common::setup_session(root);

    fs::write(root.join("test.py"), "print(1)").unwrap();

    // WHEN running add
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "test.py"])
        .assert()
        .success();

    // THEN it is persisted in the session view
    let view = crate::common::load_view(root);
    assert!(view.context_files.contains(&"test.py".to_string()));
}
