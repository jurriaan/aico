use assert_cmd::cargo_bin_cmd;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_session_list_and_fork_and_switch() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a project
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // WHEN forking a new branch
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-fork", "feature1"])
        .assert()
        .success();

    // THEN session-list shows new active branch
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("session-list")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let stdout = String::from_utf8(output).unwrap();
    assert!(stdout.contains("feature1 (active)"));

    // WHEN switching back to main
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-switch", "main"])
        .assert()
        .success();

    // THEN session-list shows main active again
    let output2 = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("session-list")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let stdout2 = String::from_utf8(output2).unwrap();
    assert!(stdout2.contains("main (active)"));
}

#[test]
fn test_load_pointer_invalid_json_exits() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a pointer file with invalid JSON
    let pointer_file = root.join(".ai_session.json");
    fs::write(&pointer_file, "not json").unwrap();

    // WHEN running status
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("AICO_SESSION_FILE", &pointer_file)
        .arg("status")
        .assert()
        .failure()
        .stderr(predicates::str::contains("Invalid pointer file format"));
}

#[test]
fn test_load_pointer_missing_view_exits() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a pointer JSON that points to a non-existent file
    let pointer_file = root.join(".ai_session.json");
    let pointer_data = serde_json::json!({
        "type": "aico_session_pointer_v1",
        "path": ".aico/sessions/missing.json"
    });
    fs::write(&pointer_file, serde_json::to_string(&pointer_data).unwrap()).unwrap();

    // WHEN running status
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("AICO_SESSION_FILE", &pointer_file)
        .arg("status")
        .assert()
        .failure()
        .stderr(predicates::str::contains("Missing view file"));
}
