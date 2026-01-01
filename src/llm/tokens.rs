use crate::model_registry::get_model_info;
use std::cmp::max;

use crate::consts::*;
use crate::models::TokenUsage;

pub async fn calculate_cost(model_id: &str, usage: &TokenUsage) -> Option<f64> {
    let info = get_model_info(model_id).await?;
    calculate_cost_prefetched(&info, usage)
}

pub fn calculate_cost_prefetched(
    info: &crate::model_registry::ModelInfo,
    usage: &TokenUsage,
) -> Option<f64> {
    let mut total_cost = 0.0;
    let mut has_cost = false;

    if let Some(input_cost) = info.input_cost_per_token {
        total_cost += usage.prompt_tokens as f64 * input_cost;
        has_cost = true;
    }

    if let Some(output_cost) = info.output_cost_per_token {
        total_cost += usage.completion_tokens as f64 * output_cost;
        has_cost = true;
    }

    if has_cost { Some(total_cost) } else { None }
}

pub struct HeuristicCounter {
    total_bytes: usize,
}

impl Default for HeuristicCounter {
    fn default() -> Self {
        Self::new()
    }
}

impl HeuristicCounter {
    pub fn new() -> Self {
        Self { total_bytes: 0 }
    }

    pub fn count(&self) -> u32 {
        (self.total_bytes as u32) / 4
    }

    pub fn add_str(&mut self, s: &str) {
        self.total_bytes += s.len();
    }
}

impl std::fmt::Write for HeuristicCounter {
    fn write_str(&mut self, s: &str) -> std::fmt::Result {
        self.total_bytes += s.len();
        Ok(())
    }
}

pub fn count_heuristic(text: &str) -> u32 {
    (text.len() as u32) / 4
}

pub fn count_tokens_for_messages(messages: &[&str]) -> u32 {
    let mut counter = HeuristicCounter::new();
    for message in messages {
        counter.add_str(message);
    }
    counter.count()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_count_heuristic() {
        assert_eq!(count_heuristic("abcd"), 1);
        assert_eq!(count_heuristic("abcdefgh"), 2);
    }
}

pub fn count_system_tokens() -> u32 {
    let system_prompt_len = DEFAULT_SYSTEM_PROMPT.len() + DIFF_MODE_INSTRUCTIONS.len();
    system_prompt_len as u32 / 4
}

pub fn count_max_alignment_tokens() -> u32 {
    let conv = count_tokens_for_messages(&[
        ALIGNMENT_CONVERSATION_USER,
        ALIGNMENT_CONVERSATION_ASSISTANT,
    ]);
    let diff = count_tokens_for_messages(&[ALIGNMENT_DIFF_USER, ALIGNMENT_DIFF_ASSISTANT]);
    let anchor_tokens = count_tokens_for_messages(&[
        STATIC_CONTEXT_INTRO,
        STATIC_CONTEXT_ANCHOR,
        FLOATING_CONTEXT_INTRO,
        FLOATING_CONTEXT_ANCHOR,
    ]);

    let base_max = max(conv, diff);

    base_max + anchor_tokens
}
