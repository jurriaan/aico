use crate::consts::SESSION_FILE_NAME;
use crate::exceptions::AicoError;
use crate::fs::atomic_write_json;
use crate::models::{SessionPointer, SessionView};
use chrono::Utc;
use std::env;
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

pub fn run(model: String) -> Result<(), AicoError> {
    let current_dir = env::current_dir()?;
    let session_file = current_dir.join(SESSION_FILE_NAME);

    if session_file.exists() {
        return Err(AicoError::Configuration(format!(
            "Session file '{}' already exists in this directory.",
            session_file.display()
        )));
    }

    // 1. Prepare directories
    let aico_dir = current_dir.join(".aico");
    let history_root = aico_dir.join("history");
    let sessions_dir = aico_dir.join("sessions");

    // Create dirs with 0700 permissions
    for dir in &[&aico_dir, &history_root, &sessions_dir] {
        fs::create_dir_all(dir)?;
        #[cfg(unix)]
        {
            let mut perms = fs::metadata(dir)?.permissions();
            perms.set_mode(0o700);
            fs::set_permissions(dir, perms)?;
        }
    }

    // 2. Create .gitignore
    let gitignore_path = aico_dir.join(".gitignore");
    if !gitignore_path.exists() {
        fs::write(&gitignore_path, "*\n!addons/\n!.gitignore\n")?;
    }

    // 3. Create SessionView
    let view = SessionView {
        model,
        context_files: vec![],
        message_indices: vec![],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: Utc::now(),
    };

    let view_path = sessions_dir.join("main.json");
    atomic_write_json(&view_path, &view)?;

    // 4. Create Pointer (relative path)
    let pointer = SessionPointer {
        pointer_type: "aico_session_pointer_v1".to_string(),
        path: ".aico/sessions/main.json".to_string(),
    };
    atomic_write_json(&session_file, &pointer)?;

    println!("Initialized session file: {}", SESSION_FILE_NAME);

    Ok(())
}
