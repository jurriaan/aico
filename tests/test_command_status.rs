mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use predicates::prelude::*;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_status_json_outputs_sorted_context_files() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with an unsorted list of context files
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "openai/test-model"])
        .assert()
        .success();

    fs::create_dir_all(root.join("src")).unwrap();
    fs::write(root.join("src/file2.ts"), "").unwrap();
    fs::write(root.join("file1.py"), "").unwrap();
    fs::write(root.join("README.md"), "").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "src/file2.ts", "file1.py", "README.md"])
        .assert()
        .success();

    // WHEN I run `aico status --json`
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .arg("--json")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    // THEN the output is a JSON object with the sorted context files
    let data: serde_json::Value = serde_json::from_slice(&output).unwrap();
    let context_files = data
        .get("context_files")
        .expect("JSON response should contain 'context_files' field")
        .as_array()
        .expect("'context_files' field should be an array");

    let actual_files: Vec<String> = context_files
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect();

    assert_eq!(actual_files, vec!["README.md", "file1.py", "src/file2.ts"]);
}

#[test]
fn test_status_table_alphabetical_sorting() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // GIVEN files added in a non-sorted order (z -> a -> m)
    fs::write(root.join("z.py"), "z").unwrap();
    fs::write(root.join("a.py"), "a").unwrap();
    fs::write(root.join("m.py"), "m").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "z.py", "a.py", "m.py"])
        .assert()
        .success();

    // WHEN running status
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();

    // THEN the files appear in alphabetical order (a, m, z)
    let a_idx = stdout.find("a.py").expect("a.py missing");
    let m_idx = stdout.find("m.py").expect("m.py missing");
    let z_idx = stdout.find("z.py").expect("z.py missing");

    assert!(a_idx < m_idx, "a.py should precede m.py in table");
    assert!(m_idx < z_idx, "m.py should precede z.py in table");
}

#[test]
fn test_status_full_breakdown_display() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with content
    fs::write(root.join("file1.py"), "a".repeat(40)).unwrap(); // ~10 tokens

    crate::common::init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file1.py"])
        .assert()
        .success();

    // WHEN running status
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .success()
        .stdout(predicate::str::contains("Session 'main'"))
        .stdout(predicate::str::contains("Tokens"))
        .stdout(predicate::str::contains("file1.py"))
        .stdout(predicate::str::contains(
            "Active window: 1 pair (IDs 0-0), 1 sent.",
        ));
}

#[test]
fn test_status_handles_dangling_messages() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with a dangling user message at the end
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "test-model"])
        .assert()
        .success();

    // Manually inject dangling message into store and view
    let view_path = root.join(".aico/sessions/main.json");
    let mut view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(&view_path).unwrap()).unwrap();

    let store_path = root.join(".aico/history");
    fs::create_dir_all(&store_path).unwrap();
    let mut store = aico::historystore::store::HistoryStore::new(store_path);

    let dangling_idx = store
        .append(&aico::models::HistoryRecord {
            role: aico::models::Role::User,
            content: "dangling question".to_string(),
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

    // WHEN running status
    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("AICO_WIDTH", "120")
        .arg("status")
        .assert()
        .success();

    let stdout =
        aico::console::strip_ansi_codes(&String::from_utf8_lossy(&assert.get_output().stdout));
    let normalized = stdout.replace('\n', " ").replace("  ", " ");
    assert!(normalized.contains("Active context contains partial/dangling messages"));
}

#[test]
fn test_status_accounts_for_piped_content_wrappers() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "openai/test-model"])
        .assert()
        .success();

    // GIVEN a session with a message that has piped content
    let view_path = root.join(".aico/sessions/main.json");
    let mut view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(&view_path).unwrap()).unwrap();

    let store_path = root.join(".aico/history");
    fs::create_dir_all(&store_path).unwrap();
    let mut store = aico::historystore::store::HistoryStore::new(store_path);

    let piped_idx = store
        .append(&aico::models::HistoryRecord {
            role: aico::models::Role::User,
            content: "the prompt".to_string(),
            mode: aico::models::Mode::Conversation,
            timestamp: chrono::Utc::now(),
            passthrough: false,
            piped_content: Some("the piped data".to_string()),
            model: None,
            token_usage: None,
            cost: None,
            duration_ms: None,
            derived: None,
            edit_of: None,
        })
        .unwrap();

    // Add a response so it's a complete pair
    let asst_idx = store
        .append(&aico::models::HistoryRecord {
            role: aico::models::Role::Assistant,
            content: "ok".to_string(),
            mode: aico::models::Mode::Conversation,
            timestamp: chrono::Utc::now(),
            passthrough: false,
            piped_content: None,
            model: Some("m".into()),
            token_usage: None,
            cost: None,
            duration_ms: None,
            derived: None,
            edit_of: None,
        })
        .unwrap();

    view.message_indices.push(piped_idx);
    view.message_indices.push(asst_idx);
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // WHEN running status --json
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["status", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let data: serde_json::Value = serde_json::from_slice(&output).unwrap();
    let tokens = data.get("total_tokens").unwrap().as_u64().unwrap();

    // THEN tokens should be > (prompt.len() + piped.len() + asst.len()) / 4
    // because of XML wrappers (<stdin_content>, <prompt>)
    let raw_sum = ("the prompt".len() + "the piped data".len() + "ok".len()) as u64 / 4;
    assert!(
        tokens > raw_sum,
        "Tokens {} should be significantly higher than raw sum {} due to XML wrapping",
        tokens,
        raw_sum
    );
}

#[test]
fn test_status_omits_excluded_messages() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 2 pairs, one excluded
    crate::common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Exclude pair 1 (r1)
    let view_path = root.join(".aico/sessions/main.json");
    let mut view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(&view_path).unwrap()).unwrap();
    view.excluded_pairs = vec![1];
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // WHEN running status
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .success()
        .stdout(predicate::str::contains("1 sent")); // Pair 0 is sent, Pair 1 is excluded.
}

#[test]
fn test_status_history_summary_logic() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with 3 pairs, start index at 1, one pair excluded
    crate::common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1"), ("p2", "r2")]);

    let view_path = root.join(".aico/sessions/main.json");
    let mut view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(&view_path).unwrap()).unwrap();

    view.history_start_pair = 1;
    view.excluded_pairs = vec![2];
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // WHEN `aico status` is run
    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("AICO_WIDTH", "120")
        .arg("status")
        .assert()
        .success();

    let stdout =
        aico::console::strip_ansi_codes(&String::from_utf8_lossy(&assert.get_output().stdout));

    // THEN it shows correct active window summary: 2 pairs (IDs 1-2), 1 sent (1 excluded)
    // We normalize whitespace/newlines to be layout-agnostic
    let normalized = stdout.replace('\n', " ").replace("  ", " ");
    assert!(normalized.contains("Active window: 2 pairs (IDs 1-2), 1 sent (1 excluded)"));
}

#[test]
fn test_status_renders_paths_with_special_characters_literal() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // GIVEN a file path with Rich-breaking characters
    let special_path = "app/[id]/(route)/page.tsx";
    let full_path = root.join(special_path);
    fs::create_dir_all(full_path.parent().unwrap()).unwrap();
    fs::write(&full_path, "content").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", special_path])
        .assert()
        .success();

    // WHEN running status
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();
    // THEN the literal path is preserved in the table
    assert!(stdout.contains(special_path));
}

#[test]
fn test_status_full_breakdown() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    fs::write(root.join("code.py"), "print(1)").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "code.py"])
        .assert()
        .success();

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();

    // Check for breakdown components
    assert!(stdout.contains("Component"));
    assert!(stdout.contains("system prompt"));
    assert!(stdout.contains("alignment prompts"));
    assert!(stdout.contains("code.py"));
    assert!(stdout.contains("Total"));
}

#[test]
fn test_status_handles_unknown_model() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "unknown/provider/model"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .success()
        .stdout(predicate::str::contains("unknown/provider/model"));
    // Cost and limit sections might be missing or zeroed, we just verify it doesn't crash.
}

#[test]
#[cfg(unix)]
fn test_status_preserves_symlink_paths() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // 1. Initialize session
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "test-model"])
        .assert()
        .success();

    // 2. Setup a file and a symlink pointing to it
    let target_dir = root.join("subdir");
    fs::create_dir_all(&target_dir).unwrap();
    let target_file = target_dir.join("actual_file.txt");
    fs::write(&target_file, "content").unwrap();

    let link_path = root.join("logical_link.txt");
    std::os::unix::fs::symlink("subdir/actual_file.txt", &link_path).unwrap();

    // 3. Add the symlink path
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "logical_link.txt"])
        .assert()
        .success();

    // 4. Verify status shows the logical name, not the canonicalized target
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .success()
        .stdout(predicate::str::contains("logical_link.txt"))
        .stdout(predicate::str::contains("actual_file.txt").not());

    // 5. Verify the view file directly for absolute certainty
    let view_path = root.join(".aico/sessions/main.json");
    let view_content = fs::read_to_string(view_path).unwrap();
    assert!(view_content.contains("\"logical_link.txt\""));
    assert!(!view_content.contains("\"actual_file.txt\""));
}

#[test]
fn test_status_fails_without_session() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // WHEN running status in an empty directory
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .failure()
        .stderr(predicate::str::contains("No session file"));
}

#[test]
fn test_status_warns_on_missing_files() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "test-model"])
        .assert()
        .success();

    // GIVEN a file added but then deleted
    fs::write(root.join("deleted.txt"), "content").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "deleted.txt"])
        .assert()
        .success();
    fs::remove_file(root.join("deleted.txt")).unwrap();

    // WHEN running status
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("status")
        .assert()
        .success()
        .stderr(predicate::str::contains(
            "Warning: Context files not found on disk: deleted.txt",
        ));
}
