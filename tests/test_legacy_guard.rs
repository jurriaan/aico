mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_load_fails_on_legacy_json() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a legacy-style session JSON (missing the pointer type)
    let legacy_json = r#"{
        "model": "gpt-4",
        "context_files": ["main.py"],
        "chat_history": []
    }"#;
    let session_file = root.join(".ai_session.json");
    fs::write(&session_file, legacy_json).unwrap();

    // WHEN attempting any command (e.g., status)
    // THEN it should fail with a specific migration message
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .failure()
        .stderr(predicates::str::contains("Invalid pointer file format"));
}

#[test]
fn test_load_fails_on_empty_file() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    let session_file = root.join(".ai_session.json");
    fs::write(&session_file, "").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .failure()
        .stderr(predicates::str::contains("Invalid pointer file format"));
}
