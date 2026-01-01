mod common;
use assert_cmd::cargo_bin_cmd;
use common::init_session_with_history;
use predicates::prelude::predicate;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_log_displays_history() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with history
    init_session_with_history(
        root,
        vec![
            ("prompt one", "response one"),
            ("prompt two", "response two"),
        ],
    );

    // Undo the last one to check display of excluded
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success();

    // WHEN 'log' is run
    let output = cargo_bin_cmd!("aico").current_dir(root).arg("log").unwrap();

    let stdout = String::from_utf8(output.stdout).unwrap();

    // THEN it shows the messages
    assert!(stdout.contains("prompt one"));
    assert!(stdout.contains("response one"));
    assert!(stdout.contains("prompt two"));

    // AND the excluded one is marked (assuming [1][-] or similar formatting)
    // The rust impl format: "1[-]"
    assert!(stdout.contains("1[-]"));
}

#[test]
fn test_log_displays_only_active_history() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with pairs
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    // AND history_start_pair is set to 1 (making pair 0 inactive)
    let view_path = root.join(".aico/sessions/main.json");
    let mut view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(&view_path).expect("read view"))
            .expect("parse view");
    view.history_start_pair = 1;
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // WHEN 'log' is run
    let output = cargo_bin_cmd!("aico").current_dir(root).arg("log").unwrap();

    let stdout = String::from_utf8(output.stdout).unwrap();

    // THEN it should NOT show pair 0 content
    assert!(!stdout.contains("p0"));
    assert!(!stdout.contains("r0"));

    // AND it should show pairs from index 1 onwards
    assert!(stdout.contains("p1"));
    assert!(stdout.contains("p2"));
}

#[test]
fn test_log_fails_without_session() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("log")
        .assert()
        .failure()
        .stderr(predicate::str::contains("No session file"));
}

#[test]
fn test_log_with_empty_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("log")
        .assert()
        .success()
        .stdout(predicate::str::contains("No message pairs found"));
}

#[test]
fn test_log_with_only_dangling_messages() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // Manually inject a dangling user message
    let view_path = root.join(".aico/sessions/main.json");
    let mut view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(&view_path).unwrap()).unwrap();

    let mut store = aico::historystore::store::HistoryStore::new(root.join(".aico/history"));
    let dangling_idx = store
        .append(&aico::models::HistoryRecord {
            role: aico::models::Role::User,
            content: "dangling content".to_string(),
            mode: aico::models::Mode::Conversation,
            timestamp: chrono::Utc::now(),
            passthrough: false,
            piped_content: None,
            model: None,
            token_usage: None,
            cost: None,
            duration_ms: None,
            derived: None,
            edit_of: None,
        })
        .unwrap();

    view.message_indices.push(dangling_idx);
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("log")
        .assert()
        .success()
        .stdout(predicate::str::contains("Dangling messages"))
        .stdout(predicate::str::contains("dangling content"));
}
