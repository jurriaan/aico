use assert_cmd::cargo_bin_cmd;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_session_new_with_model_override() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a shared-history project
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "original-model"])
        .assert()
        .success();

    // WHEN I run aico session-new new-model-session --model override-model
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args([
            "session-new",
            "new-model-session",
            "--model",
            "override-model",
        ])
        .assert()
        .success();

    // THEN the new session view uses the specified model
    let view_path = root.join(".aico/sessions/new-model-session.json");
    let content = fs::read_to_string(view_path).unwrap();
    assert!(content.contains("override-model"));
}

#[test]
fn test_session_new_fails_in_legacy_session() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a legacy (single-file) session
    let legacy_session_file = root.join(".ai_session.json");
    fs::write(
        &legacy_session_file,
        r#"{"type": "legacy", "model": "test-model", "chat_history": []}"#,
    )
    .unwrap();

    // WHEN I run aico session-new wont-work
    let cmd = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("session-new")
        .arg("wont-work")
        .assert()
        .failure();

    // THEN the command fails because it's not a shared-history session pointer
    let stderr = String::from_utf8(cmd.get_output().stderr.clone()).unwrap();
    assert!(stderr.contains("Invalid pointer file format"));
}
