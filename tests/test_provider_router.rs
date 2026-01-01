use aico::llm::client::LlmClient;
use std::env;

#[test]
fn test_get_provider_for_model_openai() {
    unsafe {
        env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let client = LlmClient::new("openai/gpt-4o").unwrap();
    assert_eq!(client.model_id, "gpt-4o");
}

#[test]
fn test_get_provider_for_model_openrouter() {
    unsafe {
        env::set_var("OPENROUTER_API_KEY", "sk-or-test");
    }
    let client = LlmClient::new("openrouter/anthropic/claude-3.5-sonnet").unwrap();
    assert_eq!(client.model_id, "anthropic/claude-3.5-sonnet");
}

#[test]
fn test_get_provider_for_model_with_params() {
    unsafe {
        env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let client = LlmClient::new("openai/o1+reasoning_effort=high").unwrap();
    assert_eq!(client.model_id, "o1");
}

#[test]
fn test_get_provider_for_model_with_multiple_params() {
    unsafe {
        env::set_var("OPENROUTER_API_KEY", "sk-or-test");
    }
    let client = LlmClient::new("openrouter/meta/llama+ext=val+effort=low").unwrap();
    assert_eq!(client.model_id, "meta/llama");
}

#[test]
fn test_get_provider_for_model_invalid_prefix() {
    let result = LlmClient::new("invalid/model");
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
    unsafe {
        env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let client = LlmClient::new("openai/gpt-4o").unwrap();
    assert_eq!(client.model_id, "gpt-4o");
}

#[test]
fn test_openai_provider_configure_request_with_reasoning_effort() {
    unsafe {
        env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let client = LlmClient::new("openai/o1+reasoning_effort=medium").unwrap();
    assert_eq!(client.model_id, "o1");
}

#[test]
fn test_openrouter_provider_configure_request() {
    unsafe {
        env::set_var("OPENROUTER_API_KEY", "sk-or-test");
    }
    let client = LlmClient::new("openrouter/anthropic/claude-3.5-sonnet").unwrap();
    assert_eq!(client.model_id, "anthropic/claude-3.5-sonnet");
}

#[test]
fn test_openrouter_provider_configure_request_with_reasoning_effort() {
    unsafe {
        env::set_var("OPENROUTER_API_KEY", "sk-or-test");
    }
    let client = LlmClient::new("openrouter/o1+reasoning_effort=high").unwrap();
    assert_eq!(client.model_id, "o1");
}
