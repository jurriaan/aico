mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use predicates::prelude::*;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_session_new_creates_empty_session_and_switches() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a project
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "original-model"])
        .assert()
        .success();

    // WHEN creating new session
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-new", "clean-slate"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Created new empty session 'clean-slate'",
        ));

    // THEN pointer updated
    let pointer = fs::read_to_string(root.join(".ai_session.json")).unwrap();
    assert!(pointer.contains("clean-slate.json"));

    // AND view exists
    let view_path = root.join(".aico/sessions/clean-slate.json");
    assert!(view_path.exists());
    let view_content = fs::read_to_string(view_path).unwrap();
    assert!(view_content.contains("original-model")); // Inherited
}

#[test]
fn test_session_new_fails_if_session_exists() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-new", "dev"])
        .assert()
        .success();

    // Try again
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-new", "dev"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("already exists"));
}

#[test]
fn test_session_switch_switches_pointer() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-new", "feature"])
        .assert()
        .success();

    // Pointer is now feature.json
    let p1 = fs::read_to_string(root.join(".ai_session.json")).unwrap();
    assert!(p1.contains("feature.json"));

    // Switch back to main
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-switch", "main"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Switched active session to: main"));

    // Pointer is now main.json
    let p2 = fs::read_to_string(root.join(".ai_session.json")).unwrap();
    assert!(p2.contains("main.json"));
}

#[test]
fn test_session_list() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-new", "dev"])
        .assert()
        .success();

    // List
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("session-list")
        .assert()
        .success()
        .stdout(predicate::str::contains("- main"))
        .stdout(predicate::str::contains("- dev (active)"));
}
