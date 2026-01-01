mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use common::load_view;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_undo_and_redo_toggle_exclusions() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with two pairs
    common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN running undo (defaults to -1)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success();

    // THEN the last pair (index 1) is excluded
    let view = load_view(root);
    assert_eq!(view.excluded_pairs, vec![1]);

    // WHEN running redo (defaults to -1)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("redo")
        .assert()
        .success();

    // THEN the exclusion is removed
    let view2 = load_view(root);
    assert!(view2.excluded_pairs.is_empty());
}

#[test]
fn test_context_files_update_via_add() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a project
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    fs::write(root.join("new.py"), "content").unwrap();

    // WHEN adding a file
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "new.py"])
        .assert()
        .success();

    // THEN the view JSON is updated
    let view = load_view(root);
    assert!(view.context_files.contains(&"new.py".to_string()));
}
