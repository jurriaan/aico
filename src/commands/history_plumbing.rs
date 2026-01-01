use crate::exceptions::AicoError;
use crate::session::Session;

pub fn run(user_id: usize, assistant_id: usize, at_index: usize) -> Result<(), AicoError> {
    let mut session = Session::load_active()?;

    // 1. Validate IDs exist in store
    let records = session.store.read_many(&[user_id, assistant_id])?;
    if records.is_empty() {
        return Err(AicoError::InvalidInput(format!(
            "Record ID {} not found in store.",
            user_id
        )));
    }
    if records.len() < 2 {
        return Err(AicoError::InvalidInput(format!(
            "Record ID {} not found in store.",
            assistant_id
        )));
    }
    if records[0].role != crate::models::Role::User {
        return Err(AicoError::InvalidInput(format!(
            "Message {} is not role 'user'.",
            user_id
        )));
    }
    if records[1].role != crate::models::Role::Assistant {
        return Err(AicoError::InvalidInput(format!(
            "Message {} is not role 'assistant'.",
            assistant_id
        )));
    }

    // 2. Splice into view
    let target_pos = at_index * 2;
    if at_index > (session.view.message_indices.len() / 2) {
        return Err(AicoError::InvalidInput(format!(
            "Index {} is out of bounds for history with {} pairs.",
            at_index,
            session.view.message_indices.len() / 2
        )));
    }

    session.view.message_indices.insert(target_pos, user_id);
    session
        .view
        .message_indices
        .insert(target_pos + 1, assistant_id);

    // 3. Shift metadata
    if session.view.history_start_pair >= at_index {
        session.view.history_start_pair += 1;
    }

    for i in 0..session.view.excluded_pairs.len() {
        if session.view.excluded_pairs[i] >= at_index {
            session.view.excluded_pairs[i] += 1;
        }
    }

    session.save_view()?;
    println!(
        "Splice complete. Inserted pair ({}, {}) at index {}.",
        user_id, assistant_id, at_index
    );

    Ok(())
}
