use crate::exceptions::AicoError;
use crate::historystore::store::HistoryStore;
use crate::models::{MessageWithContext, SessionView};

pub fn reconstruct_history(
    store: &HistoryStore,
    view: &SessionView,
    include_excluded: bool,
) -> Result<Vec<MessageWithContext>, AicoError> {
    let records = store.read_many(&view.message_indices)?;
    let mut active_history_vec = Vec::new();

    for (i, record) in records.into_iter().enumerate() {
        let pair_idx = i / 2;
        let is_excluded = view.excluded_pairs.contains(&pair_idx);
        let in_window = pair_idx >= view.history_start_pair;

        if in_window && (include_excluded || !is_excluded) {
            let item = MessageWithContext {
                record,
                global_index: view.message_indices[i],
                pair_index: pair_idx,
                is_excluded,
            };
            active_history_vec.push(item);
        }
    }

    Ok(active_history_vec)
}
