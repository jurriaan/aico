use aico::llm::client::LlmClient;

fn mock_env(key: &str) -> Option<String> {
    match key {
        "OPENAI_API_KEY" => Some("sk-test".to_string()),
        "OPENROUTER_API_KEY" => Some("sk-or-test".to_string()),
        "OPENAI_BASE_URL" => Some("http://openai-only.com".to_string()),
        "OPENROUTER_BASE_URL" => Some("http://openrouter-only.com".to_string()),
        _ => None,
    }
}

#[test]
fn test_get_provider_for_model_openai() {
    let client = LlmClient::new_with_env("openai/gpt-4o", mock_env).unwrap();
    assert_eq!(client.model_id, "gpt-4o");
}

#[test]
fn test_get_provider_for_model_openrouter() {
    let client =
        LlmClient::new_with_env("openrouter/anthropic/claude-3.5-sonnet", mock_env).unwrap();
    assert_eq!(client.model_id, "anthropic/claude-3.5-sonnet");
}

#[test]
fn test_get_provider_for_model_with_params() {
    let client = LlmClient::new_with_env("openai/o1+reasoning_effort=high", mock_env).unwrap();
    assert_eq!(client.model_id, "o1");
}

#[test]
fn test_get_provider_for_model_with_multiple_params() {
    let client =
        LlmClient::new_with_env("openrouter/meta/llama+ext=val+effort=low", mock_env).unwrap();
    assert_eq!(client.model_id, "meta/llama");
}

#[test]
fn test_get_provider_for_model_invalid_prefix() {
    let result = LlmClient::new_with_env("invalid/model", mock_env);
    assert!(result.is_err());
    assert!(
        result
            .unwrap_err()
            .to_string()
            .contains("Unrecognized provider prefix")
    );
}

#[test]
fn test_openai_provider_configure_request() {
    let client = LlmClient::new_with_env("openai/gpt-4o", mock_env).unwrap();
    assert_eq!(client.model_id, "gpt-4o");
}

#[test]
fn test_openrouter_ignores_openai_base_url() {
    let env_fn = |key: &str| -> Option<String> {
        match key {
            "OPENROUTER_API_KEY" => Some("sk-or-test".to_string()),
            "OPENAI_BASE_URL" => Some("http://openai-only.com".to_string()),
            _ => None,
        }
    };

    let client = LlmClient::new_with_env("openrouter/anthropic/claude-3", env_fn).unwrap();
    // Should fallback to default OpenRouter URL, not the OpenAI one
    assert_eq!(client.base_url(), "https://openrouter.ai/api/v1");
}

#[test]
fn test_openrouter_respects_openrouter_base_url() {
    let env_fn = |key: &str| -> Option<String> {
        match key {
            "OPENROUTER_API_KEY" => Some("sk-or-test".to_string()),
            "OPENROUTER_BASE_URL" => Some("http://my-proxy.com/v1".to_string()),
            _ => None,
        }
    };
    let client = LlmClient::new_with_env("openrouter/anthropic/claude-3", env_fn).unwrap();
    assert_eq!(client.base_url(), "http://my-proxy.com/v1");
}

#[test]
fn test_openai_ignores_openrouter_base_url() {
    let env_fn = |key: &str| -> Option<String> {
        match key {
            "OPENAI_API_KEY" => Some("sk-test".to_string()),
            "OPENROUTER_BASE_URL" => Some("http://openrouter-only.com".to_string()),
            _ => None,
        }
    };
    let client = LlmClient::new_with_env("openai/gpt-4o", env_fn).unwrap();
    // Should fallback to default OpenAI URL
    assert_eq!(client.base_url(), "https://api.openai.com/v1");
}
