mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use common::{init_session_with_history, load_view, setup_session};
use std::fs;
use tempfile::tempdir;

#[test]
fn test_session_fork_creates_new_view_and_switches() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // WHEN I fork a new session
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-fork", "forked"])
        .assert()
        .success();

    // THEN the pointer points to the new view
    let pointer_content = fs::read_to_string(root.join(".ai_session.json")).unwrap();
    let pointer: serde_json::Value = serde_json::from_str(&pointer_content).unwrap();
    assert_eq!(pointer["path"], ".aico/sessions/forked.json");

    // AND the new session view exists
    assert!(root.join(".aico/sessions/forked.json").is_file());
}

#[test]
fn test_session_fork_fails_if_name_exists() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // Create a dummy session with the name 'existing'
    let sessions_dir = root.join(".aico/sessions");
    fs::create_dir_all(&sessions_dir).unwrap();
    fs::write(sessions_dir.join("existing.json"), "{}").unwrap();

    // WHEN I try to fork with the same name
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-fork", "existing"])
        .assert()
        .failure()
        .stderr(predicates::str::contains("already exists"));
}

#[test]
fn test_session_fork_ephemeral_execution() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // Use a unique name for the ephemeral fork
    let fork_name = "ephemeral-fork";

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args([
            "session-fork",
            fork_name,
            "--ephemeral",
            "--",
            "printenv",
            "AICO_SESSION_FILE",
        ])
        .assert()
        .success();

    // THEN the ephemeral view file should have been cleaned up
    assert!(
        !root
            .join(".aico/sessions")
            .join(format!("{}.json", fork_name))
            .exists()
    );
}

#[test]
fn test_session_fork_persistent_execution() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    let fork_name = "persistent-fork";

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args([
            "session-fork",
            fork_name,
            "--",
            "printenv",
            "AICO_SESSION_FILE",
        ])
        .assert()
        .success();

    // THEN the view file SHOULD exist (ephemeral=false)
    assert!(
        root.join(".aico/sessions")
            .join(format!("{}.json", fork_name))
            .exists()
    );
}

#[test]
fn test_session_fork_executes_isolated_command() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    // WHEN I run a command inside a fork
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-fork", "isolated-run", "--", "cargo", "--version"])
        .assert()
        .success();

    // THEN the original session pointer remains on 'main'
    let pointer_content = fs::read_to_string(root.join(".ai_session.json")).unwrap();
    assert!(pointer_content.contains("main.json"));
}

#[test]
fn test_session_fork_preserves_exclusions() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    // Manually set an exclusion in main
    let view_path = root.join(".aico/sessions/main.json");
    let mut view = load_view(root);
    view.excluded_pairs = vec![1];
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // WHEN forking
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-fork", "fork-with-exclusions"])
        .assert()
        .success();

    // THEN the fork preserves the exclusion
    let forked_view_path = root.join(".aico/sessions/fork-with-exclusions.json");
    let forked_view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(forked_view_path).unwrap()).unwrap();
    assert_eq!(forked_view.excluded_pairs, vec![1]);
}

#[test]
fn test_session_fork_truncates_exclusions() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    // Exclude pairs 0 and 2
    let view_path = root.join(".aico/sessions/main.json");
    let mut view = load_view(root);
    view.excluded_pairs = vec![0, 2];
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // WHEN forking until pair 1 (truncating pair 2)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-fork", "truncated-fork", "--until-pair", "1"])
        .assert()
        .success();

    // THEN the forked view only contains exclusion for 0, as 2 was truncated
    let forked_view_path = root.join(".aico/sessions/truncated-fork.json");
    let forked_view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(forked_view_path).unwrap()).unwrap();
    assert_eq!(forked_view.excluded_pairs, vec![0]);
    assert_eq!(forked_view.message_indices.len(), 4); // 2 pairs = 4 messages
}

#[test]
fn test_session_fork_complex_args() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // Verify that complex quoted arguments are preserved correctly through the fork
    // Use 'sh -c' to verify that multiple arguments are passed as a single string where expected
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args([
            "session-fork",
            "complex-fork",
            "--ephemeral",
            "--",
            "sh",
            "-c",
            "echo 'arg1' && echo 'arg2'",
        ])
        .assert()
        .success()
        .stdout(predicates::str::contains("arg1\narg2"));
}

#[test]
fn test_session_fork_with_until_pair_out_of_range() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // No history yet, so pair 0 is out of range
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-fork", "invalid-fork", "--until-pair", "0"])
        .assert()
        .failure()
        .stderr(predicates::str::contains("out of bounds"));
}
