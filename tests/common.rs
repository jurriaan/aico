use aico::historystore::store::HistoryStore;
use aico::models::{HistoryRecord, Mode, Role, SessionPointer, SessionView};
use assert_cmd::cargo::cargo_bin_cmd;
use std::fs;
use std::path::Path;

#[allow(dead_code)]
pub fn setup_session(root: &Path) {
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .arg("--model")
        .arg("openai/test-model")
        .assert()
        .success();
}

#[allow(dead_code)]
pub fn init_session_with_history(root: &Path, pairs: Vec<(&str, &str)>) {
    let aico_dir = root.join(".aico");
    let history_dir = aico_dir.join("history");
    let sessions_dir = aico_dir.join("sessions");
    fs::create_dir_all(&history_dir).unwrap();
    fs::create_dir_all(&sessions_dir).unwrap();

    let mut store = HistoryStore::new(history_dir);
    let mut indices = Vec::new();

    for (u_content, a_content) in pairs {
        // User
        let u_rec = HistoryRecord {
            role: Role::User,
            content: u_content.to_string(),
            mode: Mode::Conversation,
            timestamp: time::OffsetDateTime::now_utc(),
            passthrough: false,
            piped_content: None,
            model: None,
            token_usage: None,
            cost: None,
            duration_ms: None,
            derived: None,
            edit_of: None,
        };
        indices.push(store.append(&u_rec).unwrap());

        // Assistant
        let a_rec = HistoryRecord {
            role: Role::Assistant,
            content: a_content.to_string(),
            mode: Mode::Conversation,
            timestamp: time::OffsetDateTime::now_utc(),
            passthrough: false,
            piped_content: None,
            model: Some("test-model".into()),
            token_usage: None,
            cost: None,
            duration_ms: None,
            derived: None,
            edit_of: None,
        };
        indices.push(store.append(&a_rec).unwrap());
    }

    let view = SessionView {
        model: "test-model".into(),
        context_files: vec![],
        message_indices: indices,
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: time::OffsetDateTime::now_utc(),
    };

    let view_path = sessions_dir.join("main.json");
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    let pointer = SessionPointer {
        pointer_type: "aico_session_pointer_v1".into(),
        path: ".aico/sessions/main.json".into(),
    };
    let pointer_path = root.join(".ai_session.json");
    fs::write(&pointer_path, serde_json::to_string(&pointer).unwrap()).unwrap();
}

#[allow(dead_code)]
pub fn load_view(root: &Path) -> SessionView {
    let path = root.join(".aico/sessions/main.json");
    let content = fs::read_to_string(path).unwrap();
    serde_json::from_str(&content).unwrap()
}
