use crate::exceptions::AicoError;
use crate::historystore::reconstruct::reconstruct_history;
use crate::session::Session;
use std::io::Write;

pub fn run() -> Result<(), AicoError> {
    let session = Session::load_active()?;
    let history_vec = reconstruct_history(&session.store, &session.view, false)?;

    let mut stdout = std::io::stdout().lock();

    for (i, item) in history_vec.iter().enumerate() {
        if i > 0 {
            writeln!(stdout, "\n")?;
        }
        write!(
            stdout,
            "<!-- llm-role: {} -->\n{}",
            item.record.role, item.record.content
        )?;
    }

    Ok(())
}
