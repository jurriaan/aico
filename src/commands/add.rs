use crate::exceptions::AicoError;
use crate::fs::validate_input_paths;
use crate::session::Session;
use std::path::PathBuf;

pub fn run(file_paths: Vec<PathBuf>) -> Result<(), AicoError> {
    let mut session = Session::load_active()?;

    // 1. Validate
    let (valid_rels, has_errors) = validate_input_paths(&session.root, &file_paths, true);

    // 2. Modify View
    let mut changed = false;
    for rel in valid_rels {
        if session.view.context_files.contains(&rel) {
            println!("File already in context: {}", rel);
        } else {
            println!("Added file to context: {}", rel);
            session.view.context_files.push(rel);
            changed = true;
        }
    }

    // 3. Save
    if changed {
        session.view.context_files.sort();
        session.save_view()?;
    }

    if has_errors {
        return Err(AicoError::InvalidInput(
            "One or more files could not be added.".into(),
        ));
    }

    Ok(())
}
