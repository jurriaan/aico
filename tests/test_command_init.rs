use assert_cmd::cargo;
use predicates::prelude::*;
use std::fs;

const SESSION_FILE_NAME: &str = ".ai_session.json";

#[test]
fn test_init_creates_session_file_in_empty_dir() {
    let temp = tempfile::tempdir().unwrap();

    let mut cmd = cargo::cargo_bin_cmd!("aico");
    cmd.current_dir(&temp)
        .arg("init")
        .assert()
        .success()
        .stdout(predicate::str::contains(format!(
            "Initialized session file: {}",
            SESSION_FILE_NAME
        )));

    // Check pointer - Verify exact JSON structure for cross-compatibility
    let pointer_path = temp.path().join(SESSION_FILE_NAME);
    assert!(pointer_path.exists());
    let pointer_content = fs::read_to_string(&pointer_path).unwrap();
    let expected_pointer_json =
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#;
    assert_eq!(pointer_content, expected_pointer_json);

    // Check view
    let view_path = temp.path().join(".aico/sessions/main.json");
    assert!(view_path.exists());
    let view_content = fs::read_to_string(view_path).unwrap();
    assert!(view_content.contains("openrouter/google/gemini-3-pro-preview"));
}

#[test]
fn test_init_fails_if_session_already_exists() {
    let temp = tempfile::tempdir().unwrap();
    let session_file = temp.path().join(SESSION_FILE_NAME);
    fs::write(&session_file, "existing").unwrap();

    let mut cmd = cargo::cargo_bin_cmd!("aico");
    cmd.current_dir(&temp)
        .arg("init")
        .assert()
        .failure() // Should exit 1
        .stderr(predicate::str::contains("already exists"));
}

#[test]
fn test_init_creates_secure_directories() {
    let temp = tempfile::tempdir().unwrap();

    let mut cmd = cargo::cargo_bin_cmd!("aico");
    cmd.current_dir(&temp).arg("init").assert().success();

    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let mode = fs::metadata(temp.path().join(".aico")).unwrap().mode();
        assert_eq!(mode & 0o777, 0o700);
    }
}

#[test]
fn test_init_creates_gitignore() {
    let temp = tempfile::tempdir().unwrap();

    assert_cmd::cargo::cargo_bin_cmd!("aico")
        .current_dir(&temp)
        .arg("init")
        .assert()
        .success();

    let gitignore_path = temp.path().join(".aico/.gitignore");
    assert!(gitignore_path.exists());
    let content = fs::read_to_string(gitignore_path).unwrap();
    assert_eq!(content, "*\n!addons/\n!.gitignore\n");
}
