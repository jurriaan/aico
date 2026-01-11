use crate::exceptions::AicoError;
use crate::session::Session;
use std::env;
use std::fs;
use std::io::IsTerminal;
use std::io::{Read, Write};
use std::process::Command;

fn run_editor(content: &str) -> Result<String, AicoError> {
    // 1. Create temp file
    let mut temp = tempfile::Builder::new().suffix(".md").tempfile()?;
    temp.write_all(content.as_bytes())?;
    let temp_path = temp.path().to_path_buf();

    // 2. Open Editor
    let editor = env::var("EDITOR").unwrap_or_else(|_| "vi".into());
    let parts = shlex::split(&editor).ok_or_else(|| {
        AicoError::Configuration(format!("Failed to parse EDITOR variable: '{}'", editor))
    })?;

    if parts.is_empty() {
        return Err(AicoError::Configuration(
            "EDITOR environment variable is empty".into(),
        ));
    }

    let status = Command::new(&parts[0])
        .args(&parts[1..])
        .arg(&temp_path)
        .status()
        .map_err(|e| {
            if e.kind() == std::io::ErrorKind::NotFound {
                AicoError::InvalidInput(format!(
                    "Editor '{}' not found. Please set $EDITOR.",
                    parts[0]
                ))
            } else {
                AicoError::Io(e)
            }
        })?;

    if !status.success() {
        return Err(AicoError::InvalidInput(format!(
            "Editor closed with exit code {}. Aborting.",
            status.code().unwrap_or(1)
        )));
    }

    // 3. Read back
    let mut buffer = String::new();
    fs::File::open(&temp_path)?.read_to_string(&mut buffer)?;
    Ok(buffer)
}

pub fn run(index_str: String, prompt_flag: bool) -> Result<(), AicoError> {
    let mut session = Session::load_active()?;
    let pair_idx = session.resolve_pair_index(&index_str)?;

    // Calculate which message within the pair to edit
    let msg_idx = if prompt_flag {
        pair_idx * 2
    } else {
        pair_idx * 2 + 1
    };

    let global_idx = session.view.message_indices[msg_idx];
    let records = session.store.read_many(&[global_idx])?;
    let record = records
        .first()
        .ok_or_else(|| AicoError::SessionIntegrity("Record not found".into()))?;

    let original_content = &record.content;

    // Detect if we have piped input. We only read from stdin if it's not a terminal.
    // To prevent hanging in tests or non-interactive environments where stdin is open but empty,
    // we use a check (if possible) or ensure our tests always provide EOF.
    // For Rust, the most reliable way to check for 'piped' input that doesn't hang
    // is often specific to the OS, but we can refine the logic to check if stdin is a terminal.

    let is_piped = !std::io::stdin().is_terminal();
    let force_editor = std::env::var("AICO_FORCE_EDITOR").is_ok();

    let new_content = if is_piped && !force_editor {
        let mut buffer = String::new();
        std::io::stdin().read_to_string(&mut buffer)?;
        buffer
    } else {
        run_editor(original_content)?
    };

    // Normalize for comparison
    let norm_new = new_content.replace("\r\n", "\n");
    let norm_old = original_content.replace("\r\n", "\n");

    if (norm_new.trim().is_empty() && is_piped && !force_editor) || norm_new == norm_old {
        println!("No changes detected. Aborting.");
        return Ok(());
    }

    // 4. Update session
    session.edit_message(msg_idx, norm_new)?;

    let target = if prompt_flag { "prompt" } else { "response" };
    println!("Updated {} for message pair {}.", target, pair_idx);

    Ok(())
}
