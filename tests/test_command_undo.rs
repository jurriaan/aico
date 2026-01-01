mod common;
use assert_cmd::cargo;
use common::{init_session_with_history, load_view};
use predicates::prelude::*;
use tempfile::tempdir;

use crate::common::setup_session;

#[test]
fn test_undo_default_marks_last_pair_excluded() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with two pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN 'undo' is run
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Marked pair at index 1 as excluded.",
        ));

    // THEN the last pair (index 1) is excluded
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![1]);
}

#[test]
fn test_undo_multiple_indices() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with two pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN 'undo 0 1' is run
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1"])
        .assert()
        .success();

    // THEN both are excluded
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![0, 1]);
}

#[test]
fn test_undo_range_syntax() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with two pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN 'undo 0..1' is run
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0..1"])
        .assert()
        .success();

    // THEN both pairs are excluded (Inclusive parity check)
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![0, 1]);
}

#[test]
fn test_undo_negative_range() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with two pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN 'undo -2..-1' is run
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "-2..-1"])
        .assert()
        .success();

    // THEN both are excluded (Relative index parity check)
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![0, 1]);
}

#[test]
fn test_undo_negative_and_positive_mix() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with three pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    // WHEN 'undo 0 -1' is run (first and last)
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "-1"])
        .assert()
        .success();

    // THEN indices 0 and 2 are excluded
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![0, 2]);
}

#[test]
fn test_undo_with_positive_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0"])
        .assert()
        .success();

    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![0]);
}

#[test]
fn test_undo_with_negative_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "-2"])
        .assert()
        .success();

    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![0]);
}

#[test]
fn test_undo_multiple_and_negative_mix() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with three pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    // WHEN 'undo 0 -1' is run (first and last)
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "-1"])
        .assert()
        .success();

    // THEN indices 0 and 2 are excluded
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![0, 2]);
}

#[test]
fn test_undo_idempotent() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    // Undo once
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success();

    // Undo again
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "No changes made (specified pairs were already excluded).",
        ));
}

#[test]
fn test_undo_and_redo_toggle_exclusions() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 3 pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    // WHEN undoing pair 1
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "1"])
        .assert()
        .success();

    // THEN pair 1 is excluded
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![1]);

    // WHEN undoing a range
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0..2"])
        .assert()
        .success();

    // THEN all in range are excluded (sorted, unique)
    let view2 = load_view(root);
    assert_eq!(view2.excluded_pairs, vec![0, 1, 2]);
}

#[test]
fn test_undo_all_already_excluded() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Exclude both
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0..1"])
        .assert()
        .success();

    // Undo again
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "No changes made (specified pairs were already excluded).",
        ));
}

#[test]
fn test_undo_fails_with_invalid_index_format() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "abc"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Invalid index 'abc'. Must be an integer.",
        ));
}

#[test]
fn test_undo_fails_with_out_of_bounds_index() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "5"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Index out of bounds. Valid indices are in the range 0 (or -1).",
        ));
}

#[test]
fn test_undo_can_exclude_pair_before_active_window_shared_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    let view_path = root.join(".aico/sessions/main.json");
    let mut view = load_view(root);
    view.history_start_pair = 1;
    std::fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0"])
        .assert()
        .success();

    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![0]);
}

#[test]
fn test_undo_mixed_sign_range_fails_safely() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN 'undo 0..-1' is run
    // Python spec: Mixed sign ranges are treated as literals and usually fail parsing
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0..-1"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("Invalid index '0..-1'"));
}

#[test]
fn test_undo_idempotent_multiple() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Undo 0 once
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0"])
        .assert()
        .success();

    // Undo 0 and 1. Only 1 is new.
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0", "1"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Marked pair at index 1 as excluded.",
        ));
}

#[test]
fn test_undo_on_already_excluded_pair_is_idempotent() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    // Undo once
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success();

    // Undo again
    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "No changes made (specified pairs were already excluded).",
        ));
}

#[test]
fn test_undo_fails_on_empty_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "No message pairs found in history",
        ));
}
