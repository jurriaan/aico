use crate::exceptions::AicoError;
use crate::historystore::store::HistoryStore;
use crate::models::{MessageWithContext, SessionView};

pub fn reconstruct_history(
    store: &HistoryStore,
    view: &SessionView,
    include_excluded: bool,
) -> Result<Vec<MessageWithContext>, AicoError> {
    let start_offset = view.history_start_pair * 2;
    if start_offset >= view.message_indices.len() {
        return Ok(Vec::new());
    }

    let active_indices = &view.message_indices[start_offset..];
    let records = store.read_many(active_indices)?;
    let mut active_history_vec = Vec::with_capacity(records.len());

    for (i, record) in records.into_iter().enumerate() {
        let abs_index = start_offset + i;
        let pair_idx = abs_index / 2;
        let is_excluded = view.excluded_pairs.contains(&pair_idx);

        if include_excluded || !is_excluded {
            active_history_vec.push(MessageWithContext {
                record,
                global_index: view.message_indices[abs_index],
                pair_index: pair_idx,
                is_excluded,
            });
        }
    }

    Ok(active_history_vec)
}
