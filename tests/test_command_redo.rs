mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use common::{init_session_with_history, load_view};
use predicates::prelude::*;
use tempfile::tempdir;

use crate::common::setup_session;

#[test]
fn test_redo_reincludes_pair() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with two pairs, where pair 1 is excluded
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success();

    // Verify setup
    assert_eq!(load_view(root).excluded_pairs, vec![1]);

    // WHEN 'redo' is run
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("redo")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Re-included pair at index 1 in context.",
        ));

    // THEN exclusions are cleared
    let view = load_view(root);
    assert!(view.excluded_pairs.is_empty());
}

#[test]
fn test_redo_range_syntax() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session where both pairs are excluded
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1"])
        .assert()
        .success();

    // WHEN 'redo 0..1' is run
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0..1"])
        .assert()
        .success();

    // THEN all exclusions are cleared
    let view = load_view(root);
    assert!(view.excluded_pairs.is_empty());
}

#[test]
fn test_redo_negative_range() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with two excluded pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1"])
        .assert()
        .success();

    // WHEN 'redo -2..-1' is run
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "-2..-1"])
        .assert()
        .success();

    // THEN all exclusions are cleared
    let view = load_view(root);
    assert!(view.excluded_pairs.is_empty());
}

#[test]
fn test_redo_default_marks_last_pair_included() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("redo")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Re-included pair at index 1 in context.",
        ));
}

#[test]
fn test_redo_multiple_indices() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1", "2"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0", "1"])
        .assert()
        .success();

    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![2]);
}

#[test]
fn test_redo_negative_and_positive_mix() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0", "-1"])
        .assert()
        .success();

    let view = load_view(root);
    assert!(view.excluded_pairs.is_empty());
}

#[test]
fn test_redo_multiple_and_negative_mix() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1", "2"])
        .assert()
        .success();

    // WHEN 'redo 0 -1' is run (first and last)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0", "-1"])
        .assert()
        .success();

    // THEN index 1 remains excluded, 0 and 2 are active
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![1]);
}

#[test]
fn test_redo_with_positive_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0"])
        .assert()
        .success();

    let view = load_view(root);
    assert!(view.excluded_pairs.is_empty());
}

#[test]
fn test_redo_with_negative_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "-2"])
        .assert()
        .success();

    let view = load_view(root);
    assert!(view.excluded_pairs.is_empty());
}

#[test]
fn test_redo_can_include_pair_before_active_window_shared_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    let view_path = root.join(".aico/sessions/main.json");
    let mut view = load_view(root);
    view.history_start_pair = 1;
    view.excluded_pairs = vec![0];
    std::fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0"])
        .assert()
        .success();

    let view = load_view(root);
    assert!(view.excluded_pairs.is_empty());
}

#[test]
fn test_redo_all_already_included() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("redo")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "No changes made (specified pairs were already active).",
        ));
}

#[test]
fn test_redo_removes_exclusion() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 3 pairs, 0 and 2 excluded
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "2"])
        .assert()
        .success();

    // WHEN redoing index 0
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0"])
        .assert()
        .success();

    // THEN 0 is removed, 2 remains
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![2]);
}

#[test]
fn test_redo_fails_with_invalid_index_format() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "abc"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Invalid index 'abc'. Must be an integer.",
        ));
}

#[test]
fn test_redo_fails_with_out_of_bounds_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "5"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Index out of bounds. Valid indices are in the range 0 (or -1).",
        ));
}

#[test]
fn test_redo_idempotent_multiple() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1"])
        .assert()
        .success();

    // Redo 0
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0"])
        .assert()
        .success();

    // Redo 0 and 1. Only 1 is new.
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["redo", "0", "1"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Re-included pair at index 1 in context.",
        ));
}

#[test]
fn test_redo_on_already_active_pair_is_idempotent() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("redo")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "No changes made (specified pairs were already active).",
        ));
}

#[test]
fn test_redo_fails_on_empty_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("redo")
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "No message pairs found in history",
        ));
}
