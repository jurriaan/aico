mod common;
use aico::historystore::store::HistoryStore;
use aico::models::{DerivedContent, DisplayItem, HistoryRecord, Mode, Role, SessionView};
use aico::session::Session;
use assert_cmd::cargo::cargo_bin_cmd;
use chrono::Utc;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_load_from_shared_history_restores_all_fields() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a shared history setup with rich metadata
    let aico_dir = root.join(".aico");
    let history_root = aico_dir.join("history");
    let sessions_dir = aico_dir.join("sessions");
    fs::create_dir_all(&history_root).unwrap();
    fs::create_dir_all(&sessions_dir).unwrap();

    let mut store = HistoryStore::new(history_root);

    let asst_derived = DerivedContent {
        unified_diff: Some("diff_content".to_string()),
        display_content: Some(vec![DisplayItem::Markdown("display_text".to_string())]),
    };

    let u_idx = store
        .append(&HistoryRecord {
            role: Role::User,
            content: "u_content".into(),
            mode: Mode::Conversation,
            timestamp: Utc::now(),
            passthrough: true,
            piped_content: Some("piped_data".into()),
            model: None,
            token_usage: None,
            cost: None,
            duration_ms: None,
            derived: None,
            edit_of: None,
        })
        .unwrap();

    let a_idx = store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "a_content".into(),
            mode: Mode::Diff,
            timestamp: Utc::now(),
            passthrough: false,
            piped_content: None,
            model: Some("m_rec".into()),
            token_usage: Some(aico::models::TokenUsage {
                prompt_tokens: 10,
                completion_tokens: 20,
                total_tokens: 30,
                cached_tokens: None,
                reasoning_tokens: None,
                cost: None,
            }),
            cost: Some(0.5),
            duration_ms: Some(500),
            derived: Some(asst_derived),
            edit_of: None,
        })
        .unwrap();

    let view = SessionView {
        model: "m_view".into(),
        context_files: vec![],
        message_indices: vec![u_idx, a_idx],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: Utc::now(),
    };
    let view_path = sessions_dir.join("main.json");
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    let pointer = aico::models::SessionPointer {
        pointer_type: "aico_session_pointer_v1".into(),
        path: ".aico/sessions/main.json".into(),
    };
    let pointer_path = root.join(".ai_session.json");
    fs::write(&pointer_path, serde_json::to_string(&pointer).unwrap()).unwrap();

    // WHEN Session is loaded
    let session = Session::load(pointer_path).expect("Should load session");

    // THEN all fields are restored correctly in the store
    let records = session
        .store
        .read_many(&session.view.message_indices)
        .unwrap();
    let user_rec = &records[0];
    let asst_rec = &records[1];

    assert_eq!(user_rec.passthrough, true);
    assert_eq!(user_rec.piped_content, Some("piped_data".to_string()));

    assert_eq!(asst_rec.model, Some("m_rec".to_string()));
    assert_eq!(asst_rec.cost, Some(0.5));
    assert_eq!(asst_rec.duration_ms, Some(500));
    assert_eq!(asst_rec.token_usage.as_ref().unwrap().prompt_tokens, 10);

    let derived = asst_rec.derived.as_ref().unwrap();
    assert_eq!(derived.unified_diff, Some("diff_content".to_string()));
}

#[test]
fn test_log_on_shared_session() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a project with shared history
    common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN running log
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("log")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();
    // THEN it shows the messages from the shared store
    assert!(stdout.contains("p0"));
    assert!(stdout.contains("r0"));
    assert!(stdout.contains("p1"));
    assert!(stdout.contains("r1"));
}

#[test]
fn test_last_on_shared_session_conversational() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a shared session with multiple pairs
    common::init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // WHEN running last (defaults to index -1)
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    // THEN it shows the latest assistant response
    assert_eq!(String::from_utf8(output).unwrap().trim(), "r1");
}

#[test]
fn test_last_on_shared_session_diff() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a shared session where an assistant message has stored derived diff content
    let aico_dir = root.join(".aico");
    fs::create_dir_all(aico_dir.join("history")).unwrap();
    fs::create_dir_all(aico_dir.join("sessions")).unwrap();

    let mut store = HistoryStore::new(aico_dir.join("history"));
    let u = store
        .append(&HistoryRecord {
            role: Role::User,
            content: "p".into(),
            mode: Mode::Diff,
            timestamp: Utc::now(),
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

    let diff_text = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n";
    let a = store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "applying change".to_string(),
            mode: Mode::Diff,
            timestamp: Utc::now(),
            passthrough: false,
            piped_content: None,
            model: Some("m".into()),
            token_usage: None,
            cost: None,
            duration_ms: None,
            derived: Some(DerivedContent {
                unified_diff: Some(diff_text.into()),
                display_content: Some(vec![DisplayItem::Diff(diff_text.into())]),
            }),
            edit_of: None,
        })
        .unwrap();

    let view = SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![u, a],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: Utc::now(),
    };
    fs::write(
        aico_dir.join("sessions/main.json"),
        serde_json::to_string(&view).unwrap(),
    )
    .unwrap();
    fs::write(
        root.join(".ai_session.json"),
        serde_json::to_string(&aico::models::SessionPointer {
            pointer_type: "aico_session_pointer_v1".into(),
            path: ".aico/sessions/main.json".into(),
        })
        .unwrap(),
    )
    .unwrap();

    // WHEN running last with pipe (non-TTY)
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    // THEN it outputs the clean unified diff from DerivedContent
    assert_eq!(String::from_utf8(output).unwrap(), diff_text);
}

#[test]
fn test_append_pair_via_ask_in_writable_shared_history() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "test-model"])
        .assert()
        .success();

    // Init some history manually since we don't have a mock LLM server in this binary test
    common::init_session_with_history(root, vec![("p0", "r0")]);
    let view_before = common::load_view(root);
    assert_eq!(view_before.message_indices.len(), 2);

    // WHEN we use a command that modifies the view (like setting history or adding files)
    // we verify the "writable" aspect of the shared history.
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "1"])
        .assert()
        .success();

    let view_after = common::load_view(root);
    assert_eq!(view_after.history_start_pair, 1);
}

#[test]
fn test_context_files_update_via_add() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a project with shared history
    common::setup_session(root);
    fs::write(root.join("extra.txt"), "hello").unwrap();

    // WHEN running add
    assert_cmd::cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "extra.txt"])
        .assert()
        .success();

    // THEN view context_files includes the file
    let view = common::load_view(root);
    assert!(view.context_files.contains(&"extra.txt".to_string()));
}

#[test]
fn test_mutating_commands_succeed_on_shared_session() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a project with a shared session
    common::setup_session(root);
    fs::write(root.join("test.txt"), "hello").unwrap();

    // WHEN running add
    assert_cmd::cargo::cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "test.txt"])
        .assert()
        .success();

    // THEN context files updated in view
    let view = common::load_view(root);
    assert!(view.context_files.contains(&"test.txt".to_string()));

    // WHEN running undo/redo
    common::init_session_with_history(root, vec![("p0", "r0")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("undo")
        .assert()
        .success();

    let view_undone = common::load_view(root);
    assert!(view_undone.excluded_pairs.contains(&0));

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("redo")
        .assert()
        .success();

    let view_redone = common::load_view(root);
    assert!(!view_redone.excluded_pairs.contains(&0));
}
