use serde::{Deserialize, Serialize};

#[derive(Serialize, Debug)]
pub struct ChatCompletionRequest {
    pub model: String,
    pub messages: Vec<Message>,
    pub stream: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stream_options: Option<StreamOptions>,
    // Allow pass-through of arbitrary "extra" fields like provider flags
    #[serde(flatten)]
    pub extra_body: Option<serde_json::Value>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct Message {
    pub role: String,
    pub content: String,
}

#[derive(Serialize, Debug)]
pub struct StreamOptions {
    pub include_usage: bool,
}

// --- Response Chunks ---

#[derive(Deserialize, Debug)]
pub struct ChatCompletionChunk {
    pub choices: Vec<ChunkChoice>,
    pub usage: Option<ApiUsage>,
}

#[derive(Deserialize, Debug)]
pub struct ChunkChoice {
    pub delta: ChunkDelta,
}

#[derive(Deserialize, Debug)]
pub struct ChunkDelta {
    pub content: Option<String>,
    #[serde(alias = "reasoning", alias = "thought", alias = "reasoning_content")]
    pub reasoning_content: Option<String>,
    #[serde(default)]
    pub reasoning_details: Option<Vec<ReasoningDetail>>,
}

#[derive(Deserialize, Debug, Clone)]
#[serde(tag = "type")]
pub enum ReasoningDetail {
    #[serde(rename = "reasoning.text")]
    Text { text: String },
    #[serde(rename = "reasoning.summary")]
    Summary { summary: String },
    #[serde(other)]
    Unknown,
}

#[derive(Deserialize, Debug, Clone)]
pub struct ApiUsage {
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_tokens: u32,
    #[serde(default)]
    pub prompt_tokens_details: Option<PromptTokensDetails>,
    #[serde(default)]
    pub completion_tokens_details: Option<CompletionTokensDetails>,
    #[serde(default)]
    pub cached_tokens: Option<u32>,
    #[serde(default)]
    pub reasoning_tokens: Option<u32>,
    #[serde(default)]
    pub cost: Option<f64>,
}

#[derive(Deserialize, Debug, Clone)]
pub struct PromptTokensDetails {
    pub cached_tokens: Option<u32>,
}

#[derive(Deserialize, Debug, Clone)]
pub struct CompletionTokensDetails {
    pub reasoning_tokens: Option<u32>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_deserialize_openai_nested_usage() {
        let json = r#"{
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "prompt_tokens_details": { "cached_tokens": 40 },
            "completion_tokens_details": { "reasoning_tokens": 20 }
        }"#;
        let usage: ApiUsage = serde_json::from_str(json).unwrap();
        assert_eq!(usage.prompt_tokens, 100);
        assert_eq!(usage.prompt_tokens_details.unwrap().cached_tokens, Some(40));
        assert_eq!(
            usage.completion_tokens_details.unwrap().reasoning_tokens,
            Some(20)
        );
    }

    #[test]
    fn test_deserialize_usage_with_cost() {
        let json = r#"{
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost": 0.00123
        }"#;
        let usage: ApiUsage = serde_json::from_str(json).unwrap();
        assert_eq!(usage.prompt_tokens, 100);
        assert_eq!(usage.cost, Some(0.00123));
    }

    #[test]
    fn test_deserialize_reasoning_details() {
        let json = r#"{
            "content": null,
            "reasoning_details": [
                { "type": "reasoning.text", "text": "planning..." },
                { "type": "reasoning.summary", "summary": "done planning" },
                { "type": "unknown_type" }
            ]
        }"#;
        let delta: ChunkDelta = serde_json::from_str(json).unwrap();
        let details = delta.reasoning_details.unwrap();
        assert_eq!(details.len(), 3);
        match &details[0] {
            ReasoningDetail::Text { text } => assert_eq!(text, "planning..."),
            _ => panic!("Expected Text"),
        }
        match &details[1] {
            ReasoningDetail::Summary { summary } => assert_eq!(summary, "done planning"),
            _ => panic!("Expected Summary"),
        }
        match &details[2] {
            ReasoningDetail::Unknown => (),
            _ => panic!("Expected Unknown"),
        }
    }
}
