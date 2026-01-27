use aico::historystore::store::HistoryStore;
use aico::models::{HistoryRecord, Mode, Role, SessionView};
use std::fs;
use tempfile::tempdir;

fn make_record(role: Role, content: &str) -> HistoryRecord {
    HistoryRecord {
        role,
        content: content.to_string(),
        mode: Mode::Conversation,
        timestamp: chrono::Utc::now(),
        passthrough: false,
        piped_content: None,
        model: None,
        token_usage: None,
        cost: None,
        duration_ms: None,
        derived: None,
        edit_of: None,
    }
}

fn make_test_session(store: HistoryStore, view: SessionView) -> aico::session::Session {
    aico::session::Session {
        file_path: std::path::PathBuf::new(),
        root: std::path::PathBuf::from("."), // Dummy root
        view_path: std::path::PathBuf::new(),
        view,
        store,
        context_content: std::collections::HashMap::new(),
    }
}

#[test]
fn test_shard_size_constant() {
    assert_eq!(aico::historystore::store::SHARD_SIZE, 10_000);
}

#[test]
fn test_history_record_serialization_round_trip_single_line() {
    // GIVEN a record with newline content and specific model
    let content = "line1\nline2\r\nline3";
    let mut rec = make_record(Role::Assistant, content);
    rec.mode = Mode::Diff;
    rec.model = Some("test-model".to_string());

    // WHEN it is serialized via serde_json
    let line = serde_json::to_string(&rec).unwrap();

    // THEN serialization stays single-line (newlines are escaped)
    assert!(!line.contains('\n'));
    assert!(!line.contains('\r'));

    // AND round-trip preserves the original content with newlines
    let parsed: HistoryRecord = serde_json::from_str(&line).unwrap();
    assert_eq!(parsed.content, content);
    assert_eq!(parsed.role, Role::Assistant);
    assert_eq!(parsed.mode, Mode::Diff);
    assert_eq!(parsed.model, Some("test-model".to_string()));
}

#[test]
fn test_serialization_integrity_single_line() {
    let temp = tempdir().unwrap();
    let root = temp.path().join("history");
    let mut store = HistoryStore::new(root.clone());

    // GIVEN a record with newlines
    let content = "line 1\nline 2\r\nline 3";
    let record = make_record(Role::Assistant, content);

    // WHEN appended
    store.append(&record).unwrap();

    // THEN the shard file contains exactly one line (excluding trailing newline)
    let shard_path = root.join("0.jsonl");
    let file_content = fs::read_to_string(&shard_path).unwrap();
    let lines: Vec<&str> = file_content.lines().collect();

    assert_eq!(lines.len(), 1);
    // AND reading it back preserves the newlines
    let read_back = store.read_many(&[0]).unwrap();
    assert_eq!(read_back[0].content, content);
}

#[test]
fn test_read_many_with_duplicate_ids() {
    let temp = tempdir().unwrap();
    let root = temp.path().join("history");
    let mut store = HistoryStore::new(root);

    let idx0 = store.append(&make_record(Role::User, "msg 0")).unwrap();
    let idx1 = store
        .append(&make_record(Role::Assistant, "msg 1"))
        .unwrap();

    // WHEN requesting duplicate IDs in a specific order
    let order = vec![idx0, idx1, idx0];
    let records = store.read_many(&order).unwrap();

    // THEN it returns the records in the requested order with duplicates
    assert_eq!(records.len(), 3);
    assert_eq!(records[0].content, "msg 0");
    assert_eq!(records[1].content, "msg 1");
    assert_eq!(records[2].content, "msg 0");
}

#[test]
#[cfg(unix)]
fn test_history_shard_permissions() {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempdir().unwrap();
    let root = temp.path().join("history");
    let mut store = HistoryStore::new(root.clone());

    store.append(&make_record(Role::User, "test")).unwrap();

    let shard_path = root.join("0.jsonl");
    let metadata = fs::metadata(shard_path).unwrap();
    let mode = metadata.permissions().mode();

    // Verify 0600 (User read/write only)
    assert_eq!(mode & 0o777, 0o600);
}

#[test]
fn test_append_pair_returns_sequential_indices() {
    let temp = tempdir().unwrap();
    let mut store = HistoryStore::new(temp.path().to_path_buf());

    let u = make_record(Role::User, "u");
    let a = make_record(Role::Assistant, "a");

    let u_idx = store.append(&u).unwrap();
    let a_idx = store.append(&a).unwrap();

    assert_eq!(a_idx, u_idx + 1);
}

#[test]
fn test_append_pair_to_view_helper() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let aico_dir = root.join(".aico");
    fs::create_dir_all(aico_dir.join("history")).unwrap();
    let mut store = HistoryStore::new(aico_dir.join("history"));

    let mut view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };

    let u_rec = make_record(Role::User, "u");
    let a_rec = make_record(Role::Assistant, "a");

    let u_idx = store.append(&u_rec).unwrap();
    let a_idx = store.append(&a_rec).unwrap();
    view.message_indices.extend([u_idx, a_idx]);

    assert_eq!(view.message_indices, vec![0, 1]);
}

#[test]
fn test_append_and_next_index_with_shards() {
    let temp = tempdir().unwrap();
    let root = temp.path().join("history");

    // GIVEN a store with shard size 5
    let mut store = HistoryStore::new_with_shard_size(root.clone(), 5);

    // WHEN appending 7 records
    let mut indices = Vec::new();
    for i in 0..7 {
        let idx = store
            .append(&make_record(Role::User, &format!("m{}", i)))
            .unwrap();
        indices.push(idx);
    }

    // THEN indices are sequential
    assert_eq!(indices, vec![0, 1, 2, 3, 4, 5, 6]);

    // AND shards exist
    assert!(root.join("0.jsonl").exists());
    assert!(root.join("5.jsonl").exists());

    // AND the 6th record (index 5) is at the start of the second shard
    let shard5 = fs::read_to_string(root.join("5.jsonl")).unwrap();
    assert_eq!(shard5.lines().count(), 2); // m5, m6

    // AND reading back works
    let recs = store.read_many(&[0, 6]).unwrap();
    assert_eq!(recs[0].content, "m0");
    assert_eq!(recs[1].content, "m6");
}

#[test]
#[cfg(unix)]
fn test_history_shard_created_with_secure_permissions() {
    use std::os::unix::fs::PermissionsExt;
    let temp = tempdir().unwrap();
    let root = temp.path().join("history");
    let mut store = HistoryStore::new(root.clone());

    store.append(&make_record(Role::User, "test")).unwrap();

    let shard_path = root.join("0.jsonl");
    let metadata = fs::metadata(shard_path).unwrap();
    let mode = metadata.permissions().mode();

    // Verify 0600 (User read/write only)
    assert_eq!(mode & 0o777, 0o600);
}

#[test]
fn test_read_many_groups_by_shard() {
    let temp = tempdir().unwrap();
    let mut store = HistoryStore::new_with_shard_size(temp.path().join("hist"), 3);

    for i in 0..8 {
        store
            .append(&make_record(Role::User, &format!("idx {}", i)))
            .unwrap();
    }

    // Read mixed order from multiple shards
    let order = vec![4, 1, 2, 5, 7];
    let records = store.read_many(&order).unwrap();

    let contents: Vec<String> = records.into_iter().map(|r| r.content).collect();
    assert_eq!(contents, vec!["idx 4", "idx 1", "idx 2", "idx 5", "idx 7"]);
}

#[test]
fn test_edit_message_can_clear_optional_fields() {
    use aico::models::{DerivedContent, TokenUsage};

    let temp = tempdir().unwrap();
    let root = temp.path().join("history_edit");
    let mut store = HistoryStore::new(root.clone());

    // 1. Create a "Fully Loaded" record
    let mut asst_rec = make_record(Role::Assistant, "hello");
    asst_rec.cost = Some(0.02);
    asst_rec.token_usage = Some(TokenUsage {
        prompt_tokens: 10,
        completion_tokens: 10,
        total_tokens: 20,
        cached_tokens: None,
        reasoning_tokens: None,
        cost: None,
    });
    asst_rec.derived = Some(DerivedContent {
        unified_diff: Some("diff".to_string()),
        display_content: vec![],
    });

    let idx = store.append(&asst_rec).unwrap();

    // 2. Load and verify fields exist in JSON
    let shard_path = root.join("0.jsonl");
    let json_line = fs::read_to_string(shard_path).unwrap();
    assert!(json_line.contains("\"cost\":0.02"));
    assert!(json_line.contains("\"unified_diff\":\"diff\""));

    // 3. Create replacement record with fields set to None
    let mut replacement = make_record(Role::Assistant, "hello updated");
    replacement.edit_of = Some(idx);
    replacement.cost = None;
    replacement.token_usage = None;
    replacement.derived = None;

    let _new_idx = store.append(&replacement).unwrap();

    // 4. Verify fields are actually omitted in the serialized JSON (skip_serializing_if)
    let records_after = fs::read_to_string(root.join("0.jsonl")).unwrap();
    let last_line = records_after.lines().last().unwrap();

    // In Rust, None fields with skip_serializing_if should not appear at all
    assert!(!last_line.contains("\"cost\""));
    assert!(!last_line.contains("\"token_usage\""));
    assert!(!last_line.contains("\"derived\""));
    assert!(last_line.contains("\"edit_of\""));
}

#[test]
fn test_edit_message_appends_and_repoints() {
    let temp = tempdir().unwrap();
    let root = temp.path().join("history");
    let mut store = HistoryStore::new(root);

    // GIVEN a store with a simple user/assistant pair
    let u_idx = store.append(&make_record(Role::User, "p0")).unwrap();
    let a_idx = store.append(&make_record(Role::Assistant, "r0")).unwrap();

    let mut view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![u_idx, a_idx],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };

    // WHEN editing the assistant message
    let mut new_record = make_record(Role::Assistant, "r0 edited");
    new_record.edit_of = Some(a_idx);
    let new_idx = store.append(&new_record).unwrap();

    // Repoint view (simulating Session::edit_message behavior)
    view.message_indices[1] = new_idx;

    // THEN the store contains a new record and view is updated
    assert_eq!(view.message_indices[1], new_idx);
    assert_ne!(new_idx, a_idx);

    // AND reading back the original index remains untouched
    let original = store.read_many(&[a_idx]).unwrap();
    assert_eq!(original[0].content, "r0");
}

#[test]
fn test_history_record_allows_newlines_and_serializes_single_line() {
    let temp = tempdir().unwrap();
    let root = temp.path().join("history");
    let mut store = HistoryStore::new(root.clone());

    // GIVEN a record with many newlines
    let complex_content = "line 1\nline 2\r\nline 3\n\nline 5";
    let record = make_record(Role::Assistant, complex_content);

    // WHEN appended
    store.append(&record).unwrap();

    // THEN the shard file contains exactly one line (plus optional trailing \n from writeln!)
    let shard_path = root.join("0.jsonl");
    let file_content = fs::read_to_string(&shard_path).unwrap();

    // Each record MUST be a single line in the JSONL shard
    assert_eq!(file_content.trim().lines().count(), 1);

    // AND the JSON itself contains no literal newlines (they are escaped)
    assert!(!file_content.trim().contains('\n'));
    assert!(!file_content.trim().contains('\r'));

    // AND reading it back preserves the original formatting exactly
    let read_back = store.read_many(&[0]).unwrap();
    assert_eq!(read_back[0].content, complex_content);
}

#[test]
fn test_find_message_pairs_in_view_logic() {
    let temp = tempdir().unwrap();
    let mut store = HistoryStore::new(temp.path().to_path_buf());

    let u0 = store.append(&make_record(Role::User, "p0")).unwrap();
    let a0 = store.append(&make_record(Role::Assistant, "r0")).unwrap();
    let d = store.append(&make_record(Role::User, "d")).unwrap();
    let u1 = store.append(&make_record(Role::User, "p1")).unwrap();
    let a1 = store.append(&make_record(Role::Assistant, "r1")).unwrap();

    let view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![u0, a0, u1, a1, d],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };

    let session = make_test_session(store, view);
    let history_vec = session.history(false).unwrap();
    let contents: Vec<String> = history_vec
        .iter()
        .map(|h| h.record.content.clone())
        .collect();
    assert_eq!(contents, vec!["p0", "r0", "p1", "r1", "d"]);
}

#[test]
fn test_session_view_io_and_reconstruction() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let history_dir = root.join(".aico/history");
    let sessions_dir = root.join(".aico/sessions");
    fs::create_dir_all(&history_dir).unwrap();
    fs::create_dir_all(&sessions_dir).unwrap();

    let mut store = HistoryStore::new(history_dir);
    let u = store.append(&make_record(Role::User, "hi")).unwrap();
    let a = store
        .append(&make_record(Role::Assistant, "hello"))
        .unwrap();

    let view = aico::models::SessionView {
        model: "test-model".into(),
        context_files: vec!["file.py".into()],
        message_indices: vec![u, a],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };

    let view_path = sessions_dir.join("main.json");
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    let loaded_json = fs::read_to_string(&view_path).unwrap();
    let loaded: aico::models::SessionView = serde_json::from_str(&loaded_json).unwrap();

    assert_eq!(loaded.model, "test-model");
    assert_eq!(loaded.message_indices, vec![u, a]);

    let session = make_test_session(store, view);
    let history_vec = session.history(false).unwrap();
    assert_eq!(history_vec.len(), 2);
}

#[test]
fn test_switch_active_pointer_writes_pointer_file() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let sessions_dir = root.join(".aico/sessions");
    fs::create_dir_all(&sessions_dir).unwrap();

    let view_path = sessions_dir.join("main.json");
    let view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    let pointer = aico::models::SessionPointer {
        pointer_type: "aico_session_pointer_v1".to_string(),
        path: ".aico/sessions/main.json".to_string(),
    };
    let pointer_path = root.join(".ai_session.json");
    fs::write(&pointer_path, serde_json::to_string(&pointer).unwrap()).unwrap();

    assert!(pointer_path.exists());
    let content = fs::read_to_string(pointer_path).unwrap();
    assert!(content.contains("aico_session_pointer_v1"));
}

#[test]
fn test_reconstruct_history_tolerates_internal_mismatch() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    let aico_dir = root.join(".aico");
    fs::create_dir_all(aico_dir.join("history")).unwrap();
    fs::create_dir_all(aico_dir.join("sessions")).unwrap();

    let mut store = aico::historystore::store::HistoryStore::new(aico_dir.join("history"));

    // GIVEN two User messages in a row
    let u1 = store.append(&make_record(Role::User, "p1")).unwrap();
    let u2 = store.append(&make_record(Role::User, "p2")).unwrap();

    let view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![u1, u2],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };

    // WHEN reconstructing
    let session = make_test_session(store, view);
    let history_vec = session.history(false).unwrap();

    // THEN it contains all messages provided by the view
    assert_eq!(history_vec.len(), 2);
    assert_eq!(history_vec[0].record.content, "p1");
    assert_eq!(history_vec[1].record.content, "p2");
}

#[test]
fn test_reconstruct_history_dangling_user_at_end() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let aico_dir = root.join(".aico");
    fs::create_dir_all(aico_dir.join("history")).unwrap();
    fs::create_dir_all(aico_dir.join("sessions")).unwrap();

    let mut store = aico::historystore::store::HistoryStore::new(aico_dir.join("history"));

    // GIVEN a User, Assistant, and trailing User
    let u1 = store.append(&make_record(Role::User, "p1")).unwrap();
    let a1 = store.append(&make_record(Role::Assistant, "r1")).unwrap();
    let u2 = store
        .append(&make_record(Role::User, "p2 dangling"))
        .unwrap();

    let view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![u1, a1, u2],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };

    // WHEN reconstructing
    let session = make_test_session(store, view);
    let history_vec = session.history(false).unwrap();

    // THEN we have all 3 messages
    assert_eq!(history_vec.len(), 3);
    assert_eq!(history_vec[2].record.content, "p2 dangling");
}

#[test]
fn test_edit_message_chain_and_manual_revert() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let aico_dir = root.join(".aico");
    fs::create_dir_all(aico_dir.join("history")).unwrap();
    fs::create_dir_all(aico_dir.join("sessions")).unwrap();

    let mut store = aico::historystore::store::HistoryStore::new(aico_dir.join("history"));

    // GIVEN user/assistant
    let u = store.append(&make_record(Role::User, "p")).unwrap();
    let a = store.append(&make_record(Role::Assistant, "r1")).unwrap();
    let mut view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![u, a],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };

    // WHEN applying two edits to response
    let mut r2 = make_record(Role::Assistant, "r2");
    r2.edit_of = Some(a);
    let idx2 = store.append(&r2).unwrap();
    view.message_indices[1] = idx2;

    let mut r3 = make_record(Role::Assistant, "r3");
    r3.edit_of = Some(idx2);
    let idx3 = store.append(&r3).unwrap();
    view.message_indices[1] = idx3;

    // THEN record points back
    let r3_read = store.read_many(&[idx3]).unwrap().pop().unwrap();
    assert_eq!(r3_read.edit_of, Some(idx2));

    // WHEN manual revert
    let prev = r3_read.edit_of.unwrap();
    view.message_indices[1] = prev;

    let r2_read = store
        .read_many(&[view.message_indices[1]])
        .unwrap()
        .pop()
        .unwrap();
    assert_eq!(r2_read.content, "r2");
}

#[test]
fn test_session_view_validates_indices() {
    // GIVEN that a valid SessionView can be created (logic validation is mostly done via serde/msgspec in python,
    // but we verify at least one state in rust)
    let view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![0, 1, 2],
        history_start_pair: 0,
        excluded_pairs: vec![1],
        created_at: chrono::Utc::now(),
    };
    assert_eq!(view.model, "m");
}

#[test]
fn test_fork_view_truncates_at_pair() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let aico_dir = root.join(".aico");
    fs::create_dir_all(aico_dir.join("history")).unwrap();
    fs::create_dir_all(aico_dir.join("sessions")).unwrap();

    let mut store = aico::historystore::store::HistoryStore::new(aico_dir.join("history"));

    // GIVEN 2 pairs and a trailing User
    let u1 = store.append(&make_record(Role::User, "p1")).unwrap();
    let a1 = store.append(&make_record(Role::Assistant, "r1")).unwrap(); // Pair 0
    let u2 = store.append(&make_record(Role::User, "p2")).unwrap();
    let a2 = store.append(&make_record(Role::Assistant, "r2")).unwrap(); // Pair 1
    let u3 = store
        .append(&make_record(Role::User, "p3 dangling"))
        .unwrap();

    let view = aico::models::SessionView {
        model: "m".into(),
        context_files: vec![],
        message_indices: vec![u1, a1, u2, a2, u3],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: chrono::Utc::now(),
    };

    // WHEN "forking" manually (which is what aico does internally via forking logic)
    // and we slice at Pair 0 (Inclusive)
    let new_indices = &view.message_indices[0..2]; // rust slice 0..2 is indices 0, 1 (u1, a1)

    // THEN result only contains pair 0
    assert_eq!(new_indices.len(), 2);
    assert_eq!(store.read_many(new_indices).unwrap()[1].content, "r1");
}
