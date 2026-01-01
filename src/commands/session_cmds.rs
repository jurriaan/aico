use crate::exceptions::AicoError;
use crate::fs::atomic_write_text;
use crate::models::{SessionView, default_timestamp};
use crate::session::Session;
use std::fs;

pub fn list() -> Result<(), AicoError> {
    let session = Session::load_active()?;
    let sessions_dir = session.sessions_dir();

    if !sessions_dir.exists() {
        return Err(AicoError::Session("Sessions directory not found.".into()));
    }

    // Get active name from the current view path
    let active_name = session
        .view_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown");

    let mut views = Vec::new();
    for entry in fs::read_dir(sessions_dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("json")
            && let Some(stem) = path.file_stem().and_then(|s| s.to_str())
        {
            views.push(stem.to_string());
        }
    }
    views.sort();

    if views.is_empty() {
        println!("No session views found.");
        return Ok(());
    }

    println!("Available sessions:");
    for name in views {
        if name == active_name {
            println!("  - {} (active)", name);
        } else {
            println!("  - {}", name);
        }
    }

    Ok(())
}

pub fn switch(name: String) -> Result<(), AicoError> {
    let session = Session::load_active()?;
    let target_path = session.get_view_path(&name);

    if !target_path.exists() {
        return Err(AicoError::InvalidInput(format!(
            "Session view '{}' not found at {}.",
            name,
            target_path.display()
        )));
    }

    session.switch_to_view(&target_path)?;
    println!("Switched active session to: {}", name);
    Ok(())
}

pub fn new_session(name: String, model: Option<String>) -> Result<(), AicoError> {
    let session = Session::load_active()?;
    let new_view_path = session.get_view_path(&name);

    if new_view_path.exists() {
        return Err(AicoError::InvalidInput(format!(
            "A session view named '{}' already exists.",
            name
        )));
    }

    let new_model = model.unwrap_or(session.view.model.clone());

    let view = SessionView {
        model: new_model.clone(),
        context_files: vec![],
        message_indices: vec![],
        history_start_pair: 0,
        excluded_pairs: vec![],
        created_at: default_timestamp(),
    };

    let json = serde_json::to_string(&view)?;
    atomic_write_text(&new_view_path, &json)?;

    session.switch_to_view(&new_view_path)?;
    println!(
        "Created new empty session '{}' with model '{}' and switched to it.",
        name, new_model
    );

    Ok(())
}
