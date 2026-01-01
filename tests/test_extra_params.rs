use aico::llm::client::LlmClient;
use serde_json::json;

#[test]
fn test_get_extra_params_types() {
    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let client =
        LlmClient::new("openai/gpt-4o+top_p=0.5+max_tokens=100+stream=true+flag+model=o1").unwrap();

    // Test various parameter types
    let params = client.get_extra_params().unwrap();

    assert_eq!(params["top_p"], json!(0.5));
    assert_eq!(params["max_tokens"], json!(100));
    assert_eq!(params["stream"], json!(true));
    assert_eq!(params["flag"], json!(true));
    assert_eq!(params["model"], json!("o1"));
}

#[test]
fn test_get_extra_params_none() {
    unsafe {
        std::env::set_var("OPENAI_API_KEY", "sk-test");
    }
    let client = LlmClient::new("openai/gpt-4o").unwrap();
    assert!(client.get_extra_params().is_none());
}
