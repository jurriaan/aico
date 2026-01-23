mod common;
use aico::llm::executor::build_request;
use aico::models::{HistoryRecord, Mode, Role, SessionView};
use chrono::{Duration, Utc};
use std::fs;
use tempfile::tempdir;

#[tokio::test]
async fn test_interleaved_chronology() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // T=0: Init Session
    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let mut session = aico::session::Session {
        file_path: root.join(".ai_session.json"),
        root: root.to_path_buf(),
        view_path: root.join(".aico/sessions/main.json"),
        view: SessionView {
            model: "openai/test-model".into(),
            context_files: vec!["file_a.py".into(), "file_b.py".into()],
            message_indices: vec![],
            history_start_pair: 0,
            excluded_pairs: vec![],
            created_at: Utc::now(),
        },
        store: aico::historystore::store::HistoryStore::new(root.join(".aico/history")),
        context_content: std::collections::HashMap::new(),
    };
    fs::create_dir_all(root.join(".aico/sessions")).unwrap();
    fs::create_dir_all(root.join(".aico/history")).unwrap();

    // Persist session setup to disk so load() can find it
    session.save_view().unwrap();
    fs::write(
        root.join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    // T=5: Create File A
    let ts_5 = Utc::now() - Duration::seconds(100);
    let file_a = root.join("file_a.py");
    fs::write(&file_a, "content_a").unwrap();
    fs::File::open(&file_a)
        .unwrap()
        .set_modified(ts_5.into())
        .unwrap();

    // T=10: Msg 1
    let ts_10 = ts_5 + Duration::seconds(5);
    let u1 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "Msg 1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10,
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
    let a1 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "Resp 1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10 + Duration::seconds(1),
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
    session.view.message_indices.extend(vec![u1, a1]);
    session.save_view().unwrap();

    // T=20: Msg 2
    let ts_20 = ts_10 + Duration::seconds(10);
    let u2 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "Msg 2".into(),
            mode: Mode::Conversation,
            timestamp: ts_20,
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
    let a2 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "Resp 2".into(),
            mode: Mode::Conversation,
            timestamp: ts_20 + Duration::seconds(1),
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
    session.view.message_indices.extend(vec![u2, a2]);
    session.save_view().unwrap();

    // T=25: Modify File B (Between Msg 2 and Prompt)
    let ts_25 = ts_20 + Duration::seconds(5);
    let file_b = root.join("file_b.py");
    fs::write(&file_b, "content_b").unwrap();
    fs::File::open(&file_b)
        .unwrap()
        .set_modified(ts_25.into())
        .unwrap();

    // Re-load session to simulate a new CLI invocation after file changes
    let session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    // T=30: Generate Request
    let req = build_request(
        &session,
        "System",
        "Prompt",
        Mode::Conversation,
        false,
        false,
    )
    .await
    .unwrap();
    let messages = req.messages;

    // 0: System
    assert_eq!(messages[0].content, "System");

    // 1-2: Static Context (File A)
    assert!(
        messages[1]
            .content
            .contains("The following XML block contains the baseline contents")
    );
    assert!(messages[1].content.contains("file_a.py"));
    assert!(!messages[1].content.contains("file_b.py"));
    assert_eq!(messages[2].content, aico::consts::STATIC_CONTEXT_ANCHOR);

    // 3: Msg 1
    assert_eq!(messages[3].content, "Msg 1");
    // 4: Resp 1
    assert_eq!(messages[4].content, "Resp 1");
    // 5: Msg 2
    assert_eq!(messages[5].content, "Msg 2");
    // 6: Resp 2
    assert_eq!(messages[6].content, "Resp 2");

    // 7-8: Floating Context (File B)
    assert!(messages[7].content.contains("UPDATED CONTEXT"));
    assert!(messages[7].content.contains("file_b.py"));
    assert_eq!(messages[8].content, aico::consts::FLOATING_CONTEXT_ANCHOR);

    // Final Prompt etc
    assert_eq!(messages.last().unwrap().content, "Prompt");
}

#[tokio::test]
async fn test_fresh_session_behavior() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let session = aico::session::Session {
        file_path: root.join(".ai_session.json"),
        root: root.to_path_buf(),
        view_path: root.join(".aico/sessions/main.json"),
        view: SessionView {
            model: "openai/test-model".into(),
            context_files: vec!["file_a.py".into()],
            message_indices: vec![],
            history_start_pair: 0,
            excluded_pairs: vec![],
            created_at: Utc::now(),
        },
        store: aico::historystore::store::HistoryStore::new(root.join(".aico/history")),
        context_content: std::collections::HashMap::new(),
    };
    fs::create_dir_all(root.join(".aico/sessions")).unwrap();
    fs::create_dir_all(root.join(".aico/history")).unwrap();

    session.save_view().unwrap();
    fs::write(
        root.join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    let file_a = root.join("file_a.py");
    fs::write(&file_a, "content_a").unwrap();

    // Re-load session to simulate a new CLI invocation after file creation
    let session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    let req = build_request(
        &session,
        "System",
        "Prompt",
        Mode::Conversation,
        false,
        false,
    )
    .await
    .unwrap();
    let messages = req.messages;

    // Fresh session = all files are baseline context
    assert!(messages[1].content.contains("baseline contents"));
    assert!(!messages[1].content.contains("UPDATED CONTEXT"));
}

#[tokio::test]
async fn test_fresh_session_baseline() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let session = aico::session::Session {
        file_path: root.join(".ai_session.json"),
        root: root.to_path_buf(),
        view_path: root.join(".aico/sessions/main.json"),
        view: SessionView {
            model: "openai/test-model".into(),
            context_files: vec!["file.py".into()],
            message_indices: vec![],
            history_start_pair: 0,
            excluded_pairs: vec![],
            created_at: Utc::now(),
        },
        store: aico::historystore::store::HistoryStore::new(root.join(".aico/history")),
        context_content: std::collections::HashMap::new(),
    };
    fs::create_dir_all(root.join(".aico/sessions")).unwrap();
    fs::create_dir_all(root.join(".aico/history")).unwrap();

    session.save_view().unwrap();
    fs::write(
        root.join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    fs::write(root.join("file.py"), "content").unwrap();

    // Re-load session to simulate a new CLI invocation after file creation
    let session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    let req = build_request(
        &session,
        "System",
        "Prompt",
        Mode::Conversation,
        false,
        false,
    )
    .await
    .unwrap();

    // In a fresh session with no history, all files must be in the STATIC baseline block.
    assert!(req.messages[1].content.contains("baseline contents"));
    assert!(req.messages[1].content.contains("file.py"));
    assert!(!req.messages[1].content.contains("UPDATED CONTEXT"));
}

#[tokio::test]
async fn test_static_context_baseline() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let session = aico::session::Session {
        file_path: root.join(".ai_session.json"),
        root: root.to_path_buf(),
        view_path: root.join(".aico/sessions/main.json"),
        view: SessionView {
            model: "openai/test-model".into(),
            context_files: vec!["baseline.py".into()],
            message_indices: vec![],
            history_start_pair: 0,
            excluded_pairs: vec![],
            created_at: Utc::now(),
        },
        store: aico::historystore::store::HistoryStore::new(root.join(".aico/history")),
        context_content: std::collections::HashMap::new(),
    };
    fs::create_dir_all(root.join(".aico/sessions")).unwrap();
    fs::create_dir_all(root.join(".aico/history")).unwrap();

    session.save_view().unwrap();
    fs::write(
        root.join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    let ts_base = Utc::now() - Duration::seconds(100);

    // File created at T=base
    let file = root.join("baseline.py");
    fs::write(&file, "v1").unwrap();
    fs::File::open(&file)
        .unwrap()
        .set_modified(ts_base.into())
        .unwrap();

    // Re-load session to simulate a new CLI invocation after file creation
    let mut session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    // History starts at T=base + 10s
    let ts_10 = ts_base + Duration::seconds(10);
    let u1 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "p1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10,
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
    let a1 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "r1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10 + Duration::seconds(1),
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
    session.view.message_indices.extend(vec![u1, a1]);
    session.save_view().unwrap();

    let req = build_request(
        &session,
        "System",
        "Prompt",
        Mode::Conversation,
        false,
        false,
    )
    .await
    .unwrap();

    // File (T=0) < Horizon (T=10) => Static Baseline
    assert!(
        req.messages[1]
            .content
            .contains("The following XML block contains the baseline contents")
    );
    assert!(req.messages[1].content.contains("baseline.py"));
}

#[tokio::test]
async fn test_floating_context_splicing() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let mut session = aico::session::Session {
        file_path: root.join(".ai_session.json"),
        root: root.to_path_buf(),
        view_path: root.join(".aico/sessions/main.json"),
        view: SessionView {
            model: "openai/test-model".into(),
            context_files: vec!["update.py".into()],
            message_indices: vec![],
            history_start_pair: 0,
            excluded_pairs: vec![],
            created_at: Utc::now(),
        },
        store: aico::historystore::store::HistoryStore::new(root.join(".aico/history")),
        context_content: std::collections::HashMap::new(),
    };
    fs::create_dir_all(root.join(".aico/sessions")).unwrap();
    fs::create_dir_all(root.join(".aico/history")).unwrap();

    session.save_view().unwrap();
    fs::write(
        root.join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    let ts_base = Utc::now() - Duration::seconds(100);

    // Initial message p1/r1 at T=10
    let ts_10 = ts_base + Duration::seconds(10);
    let u1 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "p1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10,
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
    let a1 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "r1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10 + Duration::seconds(1),
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

    // Secondary message p2/r2 at T=30
    let ts_30 = ts_base + Duration::seconds(30);
    let u2 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "p2".into(),
            mode: Mode::Conversation,
            timestamp: ts_30,
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
    let a2 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "r2".into(),
            mode: Mode::Conversation,
            timestamp: ts_30 + Duration::seconds(1),
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

    session.view.message_indices.extend(vec![u1, a1, u2, a2]);
    session.save_view().unwrap();

    // File modified at T=20 (between Pair 1 and Pair 2)
    let ts_20 = ts_base + Duration::seconds(20);
    let file = root.join("update.py");
    fs::write(&file, "v2").unwrap();
    fs::File::open(&file)
        .unwrap()
        .set_modified(ts_20.into())
        .unwrap();

    // Re-load session to simulate a new CLI invocation after file modification
    let session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    let req = build_request(
        &session,
        "System",
        "Prompt",
        Mode::Conversation,
        false,
        false,
    )
    .await
    .unwrap();
    let msgs = req.messages;

    let idx_r1 = msgs.iter().position(|m| m.content == "r1").unwrap();
    let idx_floating = msgs
        .iter()
        .position(|m| m.content.contains("UPDATED CONTEXT"))
        .unwrap();
    let idx_p2 = msgs.iter().position(|m| m.content == "p2").unwrap();

    // FLOATING block must be spliced between r1 and p2
    assert!(idx_r1 < idx_floating);
    assert!(idx_floating < idx_p2);
    assert!(msgs[idx_floating].content.contains("update.py"));
}

#[tokio::test]
async fn test_shifting_horizon() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let mut session = aico::session::Session {
        file_path: root.join(".ai_session.json"),
        root: root.to_path_buf(),
        view_path: root.join(".aico/sessions/main.json"),
        view: SessionView {
            model: "openai/test-model".into(),
            context_files: vec!["app.py".into()],
            message_indices: vec![],
            history_start_pair: 0,
            excluded_pairs: vec![],
            created_at: Utc::now(),
        },
        store: aico::historystore::store::HistoryStore::new(root.join(".aico/history")),
        context_content: std::collections::HashMap::new(),
    };
    fs::create_dir_all(root.join(".aico/sessions")).unwrap();
    fs::create_dir_all(root.join(".aico/history")).unwrap();

    session.save_view().unwrap();
    fs::write(
        root.join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    let ts_base = Utc::now() - Duration::seconds(100);

    // Turn 1: Establish horizon at T=Base + 10s
    let ts_10 = ts_base + Duration::seconds(10);
    let u1 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "p1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10,
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
    let a1 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "r1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10 + Duration::seconds(1),
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
    session.view.message_indices.extend(vec![u1, a1]);
    session.save_view().unwrap();

    // File modified at T=Base + 20s (Floating relative to Turn 1)
    let ts_20 = ts_base + Duration::seconds(20);
    let app_py = root.join("app.py");
    fs::write(&app_py, "v2").unwrap();
    fs::File::open(&app_py)
        .unwrap()
        .set_modified(chrono::DateTime::<chrono::Utc>::from(ts_20).into())
        .unwrap();

    // Re-load session to simulate a new CLI invocation after file modification
    let mut session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    // Shift window start to pair 1
    session.view.history_start_pair = 1;

    // Build request for Turn 2
    let req = build_request(&session, "System", "p2", Mode::Conversation, false, false)
        .await
        .unwrap();
    let _messages = req.messages;

    // File (T=20) is now older than window start Turn 1 (T=10).
    // Wait, parity check: In Python, if start_pair=1, only messages from pair 1 onwards are sent.
    // The horizon becomes the timestamp of the first message sent.
    // If start_pair=1 and there are no messages after pair 0, the window is empty, horizon is Year 3000.
    // Let's add a second pair to make it clear.

    let ts_30 = ts_base + Duration::seconds(30);
    let u2 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "p2".into(),
            mode: Mode::Conversation,
            timestamp: ts_30,
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
    let a2 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "r2".into(),
            mode: Mode::Conversation,
            timestamp: ts_30 + Duration::seconds(1),
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
    session.view.message_indices.extend(vec![u2, a2]);
    session.save_view().unwrap();

    // Re-load session to simulate a new CLI invocation after Pair 1 is established
    let session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    // Now horizon is ts_30 (timestamp of pair 1). ts_20 < ts_30.
    let req2 = build_request(&session, "System", "p3", Mode::Conversation, false, false)
        .await
        .unwrap();
    let msgs2 = req2.messages;

    // msg[1] should contain "baseline contents" because mtime(20) < horizon(30)
    assert!(msgs2[1].content.contains("baseline contents"));
    assert!(msgs2[1].content.contains("v2"));
    // And ensure no floating context was generated
    for m in &msgs2 {
        assert!(!m.content.contains("UPDATED CONTEXT"));
    }
}

#[tokio::test]
async fn test_multiple_updates_synchronization() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // Setup session with 2 files
    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let mut session = aico::session::Session {
        file_path: root.join(".ai_session.json"),
        root: root.to_path_buf(),
        view_path: root.join(".aico/sessions/main.json"),
        view: SessionView {
            model: "openai/test-model".into(),
            context_files: vec!["a.py".into(), "b.py".into()],
            message_indices: vec![],
            history_start_pair: 0,
            excluded_pairs: vec![],
            created_at: Utc::now(),
        },
        store: aico::historystore::store::HistoryStore::new(root.join(".aico/history")),
        context_content: std::collections::HashMap::new(),
    };
    fs::create_dir_all(root.join(".aico/sessions")).unwrap();
    fs::create_dir_all(root.join(".aico/history")).unwrap();

    session.save_view().unwrap();
    fs::write(
        root.join(".ai_session.json"),
        r#"{"type":"aico_session_pointer_v1","path":".aico/sessions/main.json"}"#,
    )
    .unwrap();

    let ts_base = Utc::now() - Duration::seconds(100);

    // T=10: Turn 1
    let ts_10 = ts_base + Duration::seconds(10);
    let u1 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "p1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10,
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
    let a1 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "r1".into(),
            mode: Mode::Conversation,
            timestamp: ts_10 + Duration::seconds(1),
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
    session.view.message_indices.extend(vec![u1, a1]);
    session.save_view().unwrap();

    // Multiple updates at different times: T=25 and T=30
    let a_py = root.join("a.py");
    let b_py = root.join("b.py");
    fs::write(&a_py, "a2").unwrap();
    fs::write(&b_py, "b2").unwrap();

    let ts_25 = ts_base + Duration::seconds(25);
    let ts_30 = ts_base + Duration::seconds(30);

    fs::File::open(&a_py)
        .unwrap()
        .set_modified(chrono::DateTime::<chrono::Utc>::from(ts_25).into())
        .unwrap();
    fs::File::open(&b_py)
        .unwrap()
        .set_modified(chrono::DateTime::<chrono::Utc>::from(ts_30).into())
        .unwrap();

    // Re-load session to simulate a new CLI invocation after multiple file modifications
    let mut session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    // T=40: Turn 2
    let ts_40 = ts_base + Duration::seconds(40);
    let u2 = session
        .store
        .append(&HistoryRecord {
            role: Role::User,
            content: "p2".into(),
            mode: Mode::Conversation,
            timestamp: ts_40,
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
    let a2 = session
        .store
        .append(&HistoryRecord {
            role: Role::Assistant,
            content: "r2".into(),
            mode: Mode::Conversation,
            timestamp: ts_40 + Duration::seconds(1),
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
    session.view.message_indices.extend(vec![u2, a2]);
    session.save_view().unwrap();

    // Re-load session to ensure Turn 2 (p2/r2) is in the session history
    let session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();

    // T=50: Build Turn 3 relative to T=40
    let req = build_request(&session, "System", "p3", Mode::Conversation, false, false)
        .await
        .unwrap();
    let messages = req.messages;

    // The logic should use max(mtime) of updates.
    // Latest Floating Mtime = T=30.
    // Splice point search: find first message > T=30.
    // Msg p2 is at T=40. So splice point is Turn 2.

    // msg[0]: System
    // msg[1-2]: Static Anchor (No static files exist here since Year 3000 logic or mtime > t10)
    // Actually, at Turn 3, Horizon is the timestamp of pair 0 (T=10).
    // All files mtime (25, 30) > T=10, so all are Floating.

    let idx_r1 = messages
        .iter()
        .position(|m| m.content == "r1")
        .expect("r1 not found");
    let idx_floating = messages
        .iter()
        .position(|m| m.content.contains("UPDATED CONTEXT"))
        .expect("Floating context not found");
    let idx_p2 = messages
        .iter()
        .position(|m| m.content == "p2")
        .expect("p2 not found");

    assert!(idx_r1 < idx_floating);
    assert!(idx_floating < idx_p2);
    assert!(messages[idx_floating].content.contains("a.py"));
    assert!(messages[idx_floating].content.contains("b.py"));
    assert!(messages[idx_floating].content.contains("a2"));
    assert!(messages[idx_floating].content.contains("b2"));
}
