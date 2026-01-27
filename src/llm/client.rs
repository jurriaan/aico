use crate::exceptions::AicoError;
use crate::llm::api_models::{ChatCompletionChunk, ChatCompletionRequest};
use crate::models::Provider;
use reqwest::Client as HttpClient;
use std::env;
use std::str::FromStr;

#[derive(Debug)]
struct ModelSpec {
    provider: Provider,
    model_id_short: String,
    extra_params: Option<serde_json::Value>,
}

impl FromStr for ModelSpec {
    type Err = AicoError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let (base_model, params_part) = s.split_once('+').unwrap_or((s, ""));
        let (provider_str, model_name) = base_model.split_once('/').ok_or_else(|| {
            AicoError::Configuration(format!(
                "Invalid model format '{}'. Expected 'provider/model'.",
                base_model
            ))
        })?;

        let provider = match provider_str {
            "openrouter" => Provider::OpenRouter,
            "openai" => Provider::OpenAI,
            _ => {
                return Err(AicoError::Configuration(format!(
                    "Unrecognized provider prefix in '{}'. Use 'openai/' or 'openrouter/'.",
                    s
                )));
            }
        };

        let mut extra_map: Option<serde_json::Map<String, serde_json::Value>> = None;

        if matches!(provider, Provider::OpenRouter) {
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

                    if matches!(provider, Provider::OpenRouter) && k == "reasoning_effort" {
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
            provider,
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

impl Provider {
    fn base_url_env_var(&self) -> &'static str {
        match self {
            Provider::OpenAI => "OPENAI_BASE_URL",
            Provider::OpenRouter => "OPENROUTER_BASE_URL",
        }
    }

    fn default_base_url(&self) -> &'static str {
        match self {
            Provider::OpenAI => "https://api.openai.com/v1",
            Provider::OpenRouter => "https://openrouter.ai/api/v1",
        }
    }

    fn api_key_env_var(&self) -> &'static str {
        match self {
            Provider::OpenAI => "OPENAI_API_KEY",
            Provider::OpenRouter => "OPENROUTER_API_KEY",
        }
    }
}

impl LlmClient {
    pub fn new(full_model_string: &str) -> Result<Self, AicoError> {
        Self::new_with_env(full_model_string, |k| env::var(k).ok())
    }

    pub fn new_with_env<F>(full_model_string: &str, env_get: F) -> Result<Self, AicoError>
    where
        F: Fn(&str) -> Option<String>,
    {
        let spec: ModelSpec = full_model_string.parse()?;

        let api_key_var = spec.provider.api_key_env_var();
        let api_key = env_get(api_key_var)
            .ok_or_else(|| AicoError::Configuration(format!("{} is required.", api_key_var)))?;

        let base_url = env_get(spec.provider.base_url_env_var())
            .unwrap_or_else(|| spec.provider.default_base_url().to_string());

        Ok(Self {
            http: crate::utils::setup_http_client(),
            api_key,
            base_url,
            model_id: spec.model_id_short,
            extra_params: spec.extra_params,
        })
    }

    pub fn base_url(&self) -> &str {
        &self.base_url
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

    fn mock_env(key: &str) -> Option<String> {
        match key {
            "OPENAI_API_KEY" => Some("sk-test".to_string()),
            "OPENROUTER_API_KEY" => Some("sk-or-test".to_string()),
            _ => None,
        }
    }

    #[test]
    fn test_get_extra_params_openrouter_nesting() {
        let client =
            LlmClient::new_with_env("openrouter/openai/o1+reasoning_effort=medium", mock_env)
                .unwrap();
        let params = client.get_extra_params().unwrap();

        assert_eq!(params["usage"]["include"], true);
        assert_eq!(params["reasoning"]["effort"], "medium");
        assert!(params.get("reasoning_effort").is_none());
    }

    #[test]
    fn test_get_extra_params_openai_flattened() {
        let client =
            LlmClient::new_with_env("openai/o1+reasoning_effort=medium", mock_env).unwrap();
        let params = client.get_extra_params().unwrap();

        assert_eq!(params["reasoning_effort"], "medium");
        assert!(params.get("usage").is_none());
    }
}
