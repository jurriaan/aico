use crate::exceptions::AicoError;
use crate::fs::atomic_write_json;
use crate::models::SessionPointer;
use crate::session::Session;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::process::Command;
use tempfile::NamedTempFile;

pub fn run(
    new_name: String,
    until_pair: Option<usize>,
    ephemeral: bool,
    exec_args: Vec<String>,
) -> Result<(), AicoError> {
    let session = Session::load_active()?;

    if new_name.trim().is_empty() {
        return Err(AicoError::InvalidInput(
            "New session name is required.".into(),
        ));
    }

    let new_view_path = session.get_view_path(&new_name);
    if new_view_path.exists() {
        return Err(AicoError::InvalidInput(format!(
            "A session view named '{}' already exists.",
            new_name
        )));
    }

    // 1. Create Forked View
    let mut new_view = session.view.clone();
    if let Some(limit) = until_pair {
        let total_pairs = new_view.message_indices.len() / 2;
        if limit >= total_pairs {
            return Err(AicoError::InvalidInput(format!(
                "Pair index {} is out of bounds. Session only has {} pairs.",
                limit, total_pairs
            )));
        }

        let truncation_len = (limit + 1) * 2;
        new_view.message_indices.truncate(truncation_len);

        // Truncate other metadata to match
        if new_view.history_start_pair > limit {
            new_view.history_start_pair = limit + 1;
        }
        new_view.excluded_pairs.retain(|&idx| idx <= limit);
    }

    atomic_write_json(&new_view_path, &new_view)?;

    if exec_args.is_empty() {
        // Standard fork: update pointer
        session.switch_to_view(&new_view_path)?;
        let truncated = until_pair
            .map(|u| format!(" (truncated at pair {})", u))
            .unwrap_or_default();
        println!(
            "Forked new session '{}'{} and switched to it.",
            new_name, truncated
        );
    } else {
        // Execute in fork: use temp pointer
        let mut temp_ptr = NamedTempFile::new_in(&session.root)?;
        let ptr_path = temp_ptr.path().to_path_buf();

        let rel_view_path = Path::new(".aico")
            .join("sessions")
            .join(format!("{}.json", new_name));
        let pointer = SessionPointer {
            pointer_type: "aico_session_pointer_v1".to_string(),
            path: rel_view_path.to_string_lossy().replace('\\', "/"),
        };
        serde_json::to_writer(&mut temp_ptr, &pointer)?;
        temp_ptr.flush()?;

        let mut cmd = Command::new(&exec_args[0]);
        cmd.args(&exec_args[1..]);
        cmd.env("AICO_SESSION_FILE", &ptr_path);

        let status = cmd.status().map_err(AicoError::Io)?;

        if ephemeral {
            let _ = fs::remove_file(&new_view_path);
        }

        if !status.success() {
            std::process::exit(status.code().unwrap_or(1));
        }
    }

    Ok(())
}
