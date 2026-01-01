use crate::exceptions::AicoError;
use crate::historystore::reconstruct::reconstruct_history;
use crate::session::Session;

pub fn run() -> Result<(), AicoError> {
    let session = Session::load_active()?;
    let history_vec = reconstruct_history(&session.store, &session.view, false)?;

    let mut log_parts = Vec::new();

    for item in history_vec {
        let role = format!("{:?}", item.record.role).to_lowercase();
        log_parts.push(format!(
            "<!-- llm-role: {} -->\n{}",
            role, item.record.content
        ));
    }

    if !log_parts.is_empty() {
        print!("{}", log_parts.join("\n\n"));
    }

    Ok(())
}
