use crate::exceptions::AicoError;
use crate::session::Session;

// --- Helpers ---

fn parse_indices(session: &Session, indices: &[String]) -> Result<Vec<usize>, AicoError> {
    let num_pairs = session.num_pairs();
    let mut result = Vec::new();
    // Default to last if empty
    if indices.is_empty() {
        if num_pairs == 0 {
            return Err(AicoError::InvalidInput(
                "No message pairs found in history.".into(),
            ));
        }
        result.push(num_pairs - 1);
        return Ok(result);
    }

    for arg in indices {
        // Handle ranges "0..2"
        if let Some((start_str, end_str)) = arg.split_once("..") {
            let is_start_neg = start_str.starts_with('-');
            let is_end_neg = end_str.starts_with('-');

            if is_start_neg != is_end_neg {
                return Err(AicoError::InvalidInput(format!(
                    "Invalid index '{}'. Mixed positive and negative indices in a range are not supported.",
                    arg
                )));
            }

            let start_idx = session.resolve_pair_index_internal(start_str, false)? as isize;
            let end_idx = session.resolve_pair_index_internal(end_str, false)? as isize;

            let step = if start_idx <= end_idx { 1 } else { -1 };
            let mut curr = start_idx;
            loop {
                result.push(curr as usize);
                if curr == end_idx {
                    break;
                }
                curr += step;
            }
        } else {
            result.push(session.resolve_pair_index_internal(arg, false)?);
        }
    }
    result.sort();
    result.dedup();
    Ok(result)
}

// --- Commands ---

pub fn undo(indices: Vec<String>) -> Result<(), AicoError> {
    let mut session = Session::load_active()?;
    let targets = parse_indices(&session, &indices)?;

    let mut actually_changed = Vec::new();
    for idx in targets {
        if !session.view.excluded_pairs.contains(&idx) {
            session.view.excluded_pairs.push(idx);
            actually_changed.push(idx);
        }
    }

    if actually_changed.is_empty() {
        println!("No changes made (specified pairs were already excluded).");
    } else {
        session.view.excluded_pairs.sort();
        session.save_view()?;

        if actually_changed.len() == 1 {
            println!("Marked pair at index {} as excluded.", actually_changed[0]);
        } else {
            actually_changed.sort();
            let joined = actually_changed
                .iter()
                .map(|i| i.to_string())
                .collect::<Vec<_>>()
                .join(", ");
            println!(
                "Marked {} pairs as excluded: {}.",
                actually_changed.len(),
                joined
            );
        }
    }
    Ok(())
}

pub fn redo(indices: Vec<String>) -> Result<(), AicoError> {
    let mut session = Session::load_active()?;
    let targets = parse_indices(&session, &indices)?;

    let mut actually_changed = Vec::new();
    let mut new_excluded = Vec::new();
    for idx in &session.view.excluded_pairs {
        if targets.contains(idx) {
            actually_changed.push(*idx);
        } else {
            new_excluded.push(*idx);
        }
    }

    if actually_changed.is_empty() {
        println!("No changes made (specified pairs were already active).");
    } else {
        session.view.excluded_pairs = new_excluded;
        session.save_view()?;

        if actually_changed.len() == 1 {
            println!(
                "Re-included pair at index {} in context.",
                actually_changed[0]
            );
        } else {
            actually_changed.sort();
            let joined = actually_changed
                .iter()
                .map(|i| i.to_string())
                .collect::<Vec<_>>()
                .join(", ");
            println!("Re-included {} pairs: {}.", actually_changed.len(), joined);
        }
    }
    Ok(())
}

pub fn set_history(index_str: String) -> Result<(), AicoError> {
    let mut session = Session::load_active()?;
    let num_pairs = session.num_pairs();

    let target = if index_str.to_lowercase() == "clear" {
        num_pairs
    } else {
        session.resolve_pair_index_internal(&index_str, true)?
    };

    if session.view.history_start_pair != target {
        session.view.history_start_pair = target;
        session.save_view()?;

        if target == 0 {
            println!("History context reset. Full chat history is now active.");
        } else if target == num_pairs {
            println!("History context cleared.");
        } else {
            println!("History context will now start at pair {}.", target);
        }
    } else {
        println!("No change.");
    }

    Ok(())
}
