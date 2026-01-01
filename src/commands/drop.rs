use crate::exceptions::AicoError;
use crate::fs::validate_input_paths;
use crate::session::Session;
use std::path::PathBuf;

pub fn run(file_paths: Vec<PathBuf>) -> Result<(), AicoError> {
    let mut session = Session::load_active()?;

    // 1. Validate (require_exists = false)
    // Note: Python drop checks validity but allows files missing from disk to be dropped from context
    let (valid_rels, has_errors) = validate_input_paths(&session.root, &file_paths, false);

    // 2. Modify View
    let mut changed = false;

    // We track explicit errors for files not in context
    let mut context_errors = false;

    for rel in valid_rels {
        if let Some(pos) = session.view.context_files.iter().position(|x| x == &rel) {
            session.view.context_files.remove(pos);
            println!("Dropped file from context: {}", rel);
            changed = true;
        } else {
            eprintln!("Error: File not in context: {}", rel);
            context_errors = true;
        }
    }

    // 3. Save
    if changed {
        session.save_view()?;
    }

    if has_errors || context_errors {
        return Err(AicoError::InvalidInput(
            "One or more files could not be dropped.".into(),
        ));
    }

    Ok(())
}
