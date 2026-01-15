use crate::exceptions::AicoError;
use crate::llm::api_models::{ChatCompletionChunk, ChatCompletionRequest};
use reqwest::Client as HttpClient;
use std::env;

#[derive(Debug)]
struct ModelSpec {
    api_key_env: &'static str,
    default_base_url: &'static str,
    model_id_short: String,
    extra_params: Option<serde_json::Value>,
}

impl ModelSpec {
    fn parse(full_str: &str) -> Result<Self, AicoError> {
        let (base_model, params_part) = full_str.split_once('+').unwrap_or((full_str, ""));
        let (provider, model_name) = base_model.split_once('/').ok_or_else(|| {
            AicoError::Configuration(format!(
                "Invalid model format '{}'. Expected 'provider/model'.",
                base_model
            ))
        })?;

        let (api_key_env, default_base_url) = match provider {
            "openrouter" => ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
            "openai" => ("OPENAI_API_KEY", "https://api.openai.com/v1"),
            _ => {
                return Err(AicoError::Configuration(format!(
                    "Unrecognized provider prefix in '{}'. Use 'openai/' or 'openrouter/'.",
                    full_str
                )));
            }
        };

        let mut extra_map: Option<serde_json::Map<String, serde_json::Value>> = None;

        if provider == "openrouter" {
            extra_map
                .get_or_insert_default()
                .insert("usage".to_string(), serde_json::json!({ "include": true }));
        }

        if !params_part.is_empty() {
            for param in params_part.split('+') {
                let m = extra_map.get_or_insert_default();
                if let Some((k, v)) = param.split_once('=') {
                    let val = serde_json::from_str::<serde_json::Value>(v)
                        .unwrap_or_else(|_| serde_json::Value::String(v.to_string()));

                    if provider == "openrouter" && k == "reasoning_effort" {
                        m.insert(
                            "reasoning".to_string(),
                            serde_json::json!({ "effort": val }),
                        );
                    } else {
                        m.insert(k.to_string(), val);
                    }
                } else {
                    m.insert(param.to_string(), serde_json::Value::Bool(true));
                }
            }
        }

        let extra_params = extra_map.map(serde_json::Value::Object);

        Ok(Self {
            api_key_env,
            default_base_url,
            model_id_short: model_name.to_string(),
            extra_params,
        })
    }
}

#[derive(Debug)]
pub struct LlmClient {
    http: HttpClient,
    api_key: String,
    base_url: String,
    pub model_id: String,
    extra_params: Option<serde_json::Value>,
}

impl LlmClient {
    pub fn new(full_model_string: &str) -> Result<Self, AicoError> {
        let spec = ModelSpec::parse(full_model_string)?;

        let api_key = env::var(spec.api_key_env)
            .map_err(|_| AicoError::Configuration(format!("{} is required.", spec.api_key_env)))?;

        let base_url =
            env::var("OPENAI_BASE_URL").unwrap_or_else(|_| spec.default_base_url.to_string());

        Ok(Self {
            http: crate::utils::setup_http_client(),
            api_key,
            base_url,
            model_id: spec.model_id_short,
            extra_params: spec.extra_params,
        })
    }

    pub fn get_extra_params(&self) -> Option<serde_json::Value> {
        self.extra_params.clone()
    }

    /// Sends a streaming request and returns a channel or iterator of chunks.
    /// For simplicity with 'minimal deps', we return the response and let the caller iterate.
    pub async fn stream_chat(
        &self,
        req: ChatCompletionRequest,
    ) -> Result<reqwest::Response, AicoError> {
        let url = format!("{}/chat/completions", self.base_url);

        let request_builder = self
            .http
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json")
            .json(&req);

        let response = request_builder
            .send()
            .await
            .map_err(|e| AicoError::Provider(e.to_string()))?;

        if !response.status().is_success() {
            let status = response.status();
            let text = response.text().await.unwrap_or_default();

            let error_msg = if text.trim().is_empty() {
                format!("API Error (Status: {}): [Empty Body]", status)
            } else {
                format!("API Error (Status: {}): {}", status, text)
            };
            return Err(AicoError::Provider(error_msg));
        }

        Ok(response)
    }
}

/// Helper to parse an SSE line: "data: {json}"
pub fn parse_sse_line(line: &str) -> Option<ChatCompletionChunk> {
    let trimmed = line.trim();
    if !trimmed.starts_with("data: ") {
        return None;
    }
    let content = &trimmed[6..];
    if content == "[DONE]" {
        return None;
    }
    serde_json::from_str(content).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_extra_params_openrouter_nesting() {
        unsafe { std::env::set_var("OPENROUTER_API_KEY", "sk-test") };
        let client = LlmClient::new("openrouter/openai/o1+reasoning_effort=medium").unwrap();
        let params = client.get_extra_params().unwrap();

        assert_eq!(params["usage"]["include"], true);
        assert_eq!(params["reasoning"]["effort"], "medium");
        assert!(params.get("reasoning_effort").is_none());
    }

    #[test]
    fn test_get_extra_params_openai_flattened() {
        unsafe { std::env::set_var("OPENAI_API_KEY", "sk-test") };
        let client = LlmClient::new("openai/o1+reasoning_effort=medium").unwrap();
        let params = client.get_extra_params().unwrap();

        assert_eq!(params["reasoning_effort"], "medium");
        assert!(params.get("usage").is_none());
    }
}
