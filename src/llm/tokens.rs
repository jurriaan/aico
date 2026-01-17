use crate::model_registry::get_model_info;

use crate::consts::*;
use crate::models::TokenUsage;

pub async fn calculate_cost(model_id: &str, usage: &TokenUsage) -> Option<f64> {
    if let Some(cost) = usage.cost {
        return Some(cost);
    }
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
        (self.total_bytes as u32).div_ceil(4)
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
    (text.len() as u32).div_ceil(4)
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

    #[tokio::test]
    async fn test_calculate_cost_priority() {
        let usage = TokenUsage {
            prompt_tokens: 10,
            completion_tokens: 10,
            total_tokens: 20,
            cached_tokens: None,
            reasoning_tokens: None,
            cost: Some(1.234),
        };

        let cost = calculate_cost("non-existent-model", &usage).await;
        assert_eq!(cost, Some(1.234));
    }
}

pub const SYSTEM_TOKEN_COUNT: u32 =
    ((DEFAULT_SYSTEM_PROMPT.len() + DIFF_MODE_INSTRUCTIONS.len()) as u32).div_ceil(4);

pub const MAX_ALIGNMENT_TOKENS: u32 = {
    let conv = ((ALIGNMENT_CONVERSATION_USER.len() + ALIGNMENT_CONVERSATION_ASSISTANT.len())
        as u32)
        .div_ceil(4);
    let diff = ((ALIGNMENT_DIFF_USER.len() + ALIGNMENT_DIFF_ASSISTANT.len()) as u32).div_ceil(4);
    let anchor_tokens = ((STATIC_CONTEXT_INTRO.len()
        + STATIC_CONTEXT_ANCHOR.len()
        + FLOATING_CONTEXT_INTRO.len()
        + FLOATING_CONTEXT_ANCHOR.len()) as u32)
        .div_ceil(4);

    let base_max = if conv > diff { conv } else { diff };
    base_max + anchor_tokens
};
