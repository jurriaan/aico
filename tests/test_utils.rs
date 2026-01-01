mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use predicates::prelude::*;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_aico_session_file_env_var_works() {
    let temp = tempdir().unwrap();
    let _root = temp.path();

    // GIVEN a session file at a non-standard location
    let custom_dir = temp.path().join("custom");
    fs::create_dir_all(&custom_dir).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(&custom_dir)
        .args(["init", "--model", "custom-model"])
        .assert()
        .success();

    let session_file = custom_dir.join(".ai_session.json");
    let session_file_abs = fs::canonicalize(session_file).unwrap();

    // WHEN running status from a different directory but with AICO_SESSION_FILE set
    let other_dir = temp.path().join("other");
    fs::create_dir_all(&other_dir).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(&other_dir)
        .env("AICO_SESSION_FILE", &session_file_abs)
        .arg("status")
        .assert()
        .success()
        .stdout(predicate::str::contains("custom-model"));
}

#[test]
fn test_aico_session_file_env_var_fails_for_relative_path() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("AICO_SESSION_FILE", "relative/ptr.json")
        .arg("status")
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "AICO_SESSION_FILE must be an absolute path",
        ));
}

#[test]
fn test_aico_session_file_env_var_fails_for_nonexistent_file() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    let nonexistent = root.join("missing.json");

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("AICO_SESSION_FILE", nonexistent)
        .arg("status")
        .assert()
        .failure()
        .stderr(predicate::str::contains("does not exist"));
}

#[test]
fn test_count_tokens_for_messages() {
    let messages = vec!["hello", "world"];
    let token_count = aico::llm::tokens::count_tokens_for_messages(&messages);
    // (5 + 5) / 4 = 2 (standard heuristic)
    assert_eq!(token_count, 2);
}

#[test]
fn test_token_formatting_logic() {
    // Test k-formatting helper
    assert_eq!(aico::console::format_tokens(1500), "1.5k");
    assert_eq!(aico::console::format_tokens(999), "999");
    assert_eq!(aico::console::format_tokens(54467), "54.5k");

    // Test thousands formatting
    assert_eq!(aico::console::format_thousands(1500), "1,500");
    assert_eq!(aico::console::format_thousands(999), "999");
    assert_eq!(aico::console::format_thousands(54467), "54,467");
}

#[test]
fn test_aico_session_file_env_var_not_set_uses_upward_search() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let project_dir = root.join("project");
    let sub_dir = project_dir.join("subdir");
    fs::create_dir_all(&sub_dir).unwrap();

    // Init in project root
    cargo_bin_cmd!("aico")
        .current_dir(&project_dir)
        .args(["init", "--model", "upward-model"])
        .assert()
        .success();

    // WHEN running status from deep subdir
    cargo_bin_cmd!("aico")
        .current_dir(&sub_dir)
        .arg("status")
        .assert()
        .success()
        .stdout(predicate::str::contains("upward-model"));
}

#[test]
fn test_calculate_and_display_cost_shows_cached_tokens() {
    use aico::historystore::store::HistoryStore;
    use aico::models::SessionView;
    use aico::models::TokenUsage;
    use chrono::Utc;

    let temp = tempdir().unwrap();
    let root = temp.path();
    let history_root = root.join("history");
    fs::create_dir_all(&history_root).unwrap();

    let store = HistoryStore::new(history_root);
    let view = SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: Utc::now(),
    };

    let usage = TokenUsage {
        prompt_tokens: 2000,
        completion_tokens: 500,
        total_tokens: 2500,
        cached_tokens: Some(1000),
        reasoning_tokens: None,
        cost: None,
    };

    // This primarily tests that display_cost_summary doesn't crash
    // and handles the optional cached_tokens field logic internally.
    aico::console::display_cost_summary(&usage, Some(0.5), &store, &view);
}

#[test]
fn test_aico_session_file_upward_search() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let project_dir = root.join("project");
    let sub_dir = project_dir.join("sub/dir");
    fs::create_dir_all(&sub_dir).unwrap();

    // Init in project root
    cargo_bin_cmd!("aico")
        .current_dir(&project_dir)
        .args(["init", "--model", "upward-model"])
        .assert()
        .success();

    // WHEN running status from deep subdir
    cargo_bin_cmd!("aico")
        .current_dir(&sub_dir)
        .arg("status")
        .assert()
        .success()
        .stdout(predicate::str::contains("upward-model"));
}
