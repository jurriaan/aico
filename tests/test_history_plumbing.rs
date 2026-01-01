mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use common::{init_session_with_history, load_view};
use std::fs;
use tempfile::tempdir;

#[test]
fn test_history_splice_inserts_correctly() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 2 pairs (IDs 0,1 and 2,3)
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN running history-splice to insert pair (0,1) at index 1
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["history-splice", "0", "1", "--at-index", "1"])
        .assert()
        .success();

    // THEN the view should have 3 pairs total (6 indices)
    let view = load_view(root);
    assert_eq!(view.message_indices.len(), 6);
    // Index 1 (pairs) is 0,1. Global indices at 2 and 3 should be 0 and 1.
    assert_eq!(view.message_indices[2], 0);
    assert_eq!(view.message_indices[3], 1);
}

#[test]
fn test_history_splice_allows_append_at_end() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN 1 pair (indices 0, 1)
    init_session_with_history(root, vec![("p0", "r0")]);

    // WHEN splicing at index 1 (the end)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["history-splice", "0", "1", "--at-index", "1"])
        .assert()
        .success();

    let view = load_view(root);
    assert_eq!(view.message_indices.len(), 4);
    assert_eq!(view.message_indices[2], 0);
    assert_eq!(view.message_indices[3], 1);
}

#[test]
fn test_history_splice_fails_invalid_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    // WHEN splicing at an out-of-bounds index 5
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["history-splice", "0", "1", "--at-index", "5"])
        .assert()
        .failure()
        .stderr(predicates::str::contains("Index 5 is out of bounds"));
}

#[test]
fn test_history_splice_validates_user_role() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    // IDs in store: 1 (User), 2 (Assistant) if init_session_with_history uses 1-based or 0-based
    // Based on Session::fetch_pair context, it fetches IDs from view.message_indices.
    let view = load_view(root);
    let _u_id = view.message_indices[0];
    let a_id = view.message_indices[1];

    // Try to use the Assistant ID as the User ID
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args([
            "history-splice",
            &a_id.to_string(),
            &a_id.to_string(),
            "--at-index",
            "0",
        ])
        .assert()
        .failure()
        .stderr(predicates::str::contains("is not role 'user'"));
}

#[test]
fn test_history_splice_validates_assistant_role() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    let view = load_view(root);
    let u_id = view.message_indices[0];

    // Try to use the User ID as the Assistant ID
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args([
            "history-splice",
            &u_id.to_string(),
            &u_id.to_string(),
            "--at-index",
            "0",
        ])
        .assert()
        .failure()
        .stderr(predicates::str::contains("is not role 'assistant'"));
}

#[test]
fn test_history_splice_updates_metadata() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Set some metadata that should shift
    let view_path = root.join(".aico/sessions/main.json");
    let mut view = load_view(root);
    view.history_start_pair = 1;
    view.excluded_pairs = vec![1];
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // Splice at index 0
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["history-splice", "0", "1", "--at-index", "0"])
        .assert()
        .success();

    let updated = load_view(root);
    assert_eq!(updated.history_start_pair, 2);
    assert_eq!(updated.excluded_pairs, vec![2]);
}

#[test]
fn test_history_splice_shifts_metadata_pointers() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Set some metadata that should shift
    let view_path = root.join(".aico/sessions/main.json");
    let mut view = load_view(root);
    view.history_start_pair = 1;
    view.excluded_pairs = vec![1];
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // Splice at index 0
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["history-splice", "0", "1", "--at-index", "0"])
        .assert()
        .success();

    let updated = load_view(root);
    assert_eq!(updated.history_start_pair, 2);
    assert_eq!(updated.excluded_pairs, vec![2]);
}

#[test]
fn test_history_splice_preserves_pointers_before_splice_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Set history_start_pair to 0 (default) and exclude nothing
    let view_path = root.join(".aico/sessions/main.json");
    let mut view = load_view(root);
    view.history_start_pair = 0;
    view.excluded_pairs = vec![];
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // Splice at index 1 (between pair 0 and pair 1)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["history-splice", "0", "1", "--at-index", "1"])
        .assert()
        .success();

    let updated = load_view(root);
    // index 0 pointers should be unchanged
    assert_eq!(updated.history_start_pair, 0);
    assert!(updated.excluded_pairs.is_empty());
}

#[test]
fn test_history_splice_fails_invalid_ids() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    // Use IDs that definitely don't exist (999, 1000)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["history-splice", "999", "1000", "--at-index", "0"])
        .assert()
        .failure()
        .stderr(predicates::str::contains("Record ID 999 not found"));
}

#[test]
fn test_history_splice_bounds_check() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    // Splicing at index 5 when only 1 pair exists
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["history-splice", "0", "1", "--at-index", "5"])
        .assert()
        .failure()
        .stderr(predicates::str::contains("out of bounds"));
}
