mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use common::init_session_with_history;
use predicates::prelude::*;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_set_history_with_negative_index_argument() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(
        root,
        vec![
            ("p0", "r0"),
            ("p1", "r1"),
            ("p2", "r2"),
            ("p3", "r3"),
            ("p4", "r4"),
        ],
    );

    // WHEN `aico set-history -2` is run
    // The resolved index of -2 in a 5-pair list is 3.
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "-2"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "History context will now start at pair 3.",
        ));

    let view = common::load_view(root);
    assert_eq!(view.history_start_pair, 3);
}

#[test]
fn test_set_history_updates_history_start_pair() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN setting history start to the second pair via CLI
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "1"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "History context will now start at pair 1.",
        ));

    // THEN view history_start_pair is updated
    let view = common::load_view(root);
    assert_eq!(view.history_start_pair, 1);
}

#[test]
fn test_set_history_updates_shared_history_view() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN setting history start to the second pair via CLI
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "1"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "History context will now start at pair 1.",
        ));

    // THEN the underlying view file is updated on disk
    let view = common::load_view(root);
    assert_eq!(view.history_start_pair, 1);
}

#[test]
fn test_set_history_with_positive_pair_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "1"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "History context will now start at pair 1.",
        ));

    let view = common::load_view(root);
    assert_eq!(view.history_start_pair, 1);
}

#[test]
fn test_set_history_to_clear_context() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN running with index equal to num_pairs (2)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "2"])
        .assert()
        .success()
        .stdout(predicate::str::contains("History context cleared."));

    let view = common::load_view(root);
    assert_eq!(view.history_start_pair, 2);
}

#[test]
fn test_set_history_with_clear_keyword() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "clear"])
        .assert()
        .success()
        .stdout(predicate::str::contains("History context cleared."));

    let view = common::load_view(root);
    assert_eq!(view.history_start_pair, 2);
}

#[test]
fn test_set_history_with_zero_sets_index_to_zero() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p", "r")]);

    // Manually set it to 1 first
    let view_path = root.join(".aico/sessions/main.json");
    let mut view = common::load_view(root);
    view.history_start_pair = 1;
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "0"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "History context reset. Full chat history is now active.",
        ));

    let updated = common::load_view(root);
    assert_eq!(updated.history_start_pair, 0);
}

#[test]
fn test_set_history_fails_with_invalid_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "3"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("Index out of bounds. Valid indices are in the range 0 to 0 (or -1 to -1) (or 1 to clear context)"));
}

#[test]
fn test_set_history_fails_with_invalid_index_shared_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "5"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("Index out of bounds. Valid indices are in the range 0 to 1 (or -1 to -2) (or 2 to clear context)"));
}

#[test]
fn test_set_history_fails_without_session() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "0"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "No session file '.ai_session.json' found.",
        ));
}

#[test]
fn test_set_history_can_move_pointer_backwards() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Set to 2 (clear)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "2"])
        .assert()
        .success();

    // Move back to 0
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "0"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "History context reset. Full chat history is now active.",
        ));

    let view = common::load_view(root);
    assert_eq!(view.history_start_pair, 0);
}

#[test]
fn test_set_history_can_move_pointer_backwards_shared_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Force start_pair to 2 in the view
    let view_path = root.join(".aico/sessions/main.json");
    let mut view = common::load_view(root);
    view.history_start_pair = 2;
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "1"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "History context will now start at pair 1.",
        ));

    let updated = common::load_view(root);
    assert_eq!(updated.history_start_pair, 1);
}

#[test]
fn test_set_history_clear_uses_full_history_in_shared_session() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "clear"])
        .assert()
        .success()
        .stdout(predicate::str::contains("History context cleared."));

    let view = common::load_view(root);
    assert_eq!(view.history_start_pair, 3);
}
