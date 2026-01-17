use aico::model_registry::get_model_info_at;
use mockito::Server;
use serde_json::json;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_get_model_info_lookup_strategies() {
    let temp = tempdir().unwrap();
    let cache_dir = temp.path().join("aico");
    fs::create_dir_all(&cache_dir).unwrap();

    let registry_json = r#"{
        "last_fetched": "2023-01-01T00:00:00Z",
        "models": {
            "gpt-4o": { "max_input_tokens": 100 },
            "gpt-5.2": { "max_input_tokens": 101 },
            "google/gemini-pro": { "max_input_tokens": 200 },
            "openrouter/openai/gpt-4o": { "max_input_tokens": 150 }
        }
    }"#;
    let cache_path = cache_dir.join("models.json");
    fs::write(&cache_path, registry_json).unwrap();

    let info = get_model_info_at("gpt-4o", cache_path.clone());
    assert_eq!(info.unwrap().max_input_tokens, Some(100));

    let stripped = get_model_info_at("openai/gpt-4o", cache_path.clone());
    assert_eq!(stripped.unwrap().max_input_tokens, Some(100));

    // 3. Match with +flags
    let with_flags = get_model_info_at("openai/gpt-4o+reasoning_effort=medium", cache_path.clone());
    assert_eq!(with_flags.unwrap().max_input_tokens, Some(100));

    // 4. Match with :modifiers (fallback to partially qualified name)
    // This handles cases like openrouter/openai/gpt-4o:online -> openrouter/openai/gpt-4o
    let with_modifier = get_model_info_at("openrouter/openai/gpt-4o:online", cache_path.clone());
    assert_eq!(
        with_modifier
            .expect("Should find info for model with modifier")
            .max_input_tokens,
        Some(150),
        "Should prioritize openrouter/openai/gpt-4o over the root gpt-4o entry"
    );

    // 5. Deep fallback: if modifier stripping on full name fails, it should still find gpt-4o
    let with_modifier_stripped = get_model_info_at("openrouter/openai/gpt-5.2:online", cache_path);
    assert_eq!(
        with_modifier_stripped
            .expect("Should find info for model with modifier")
            .max_input_tokens,
        Some(101),
        "Should fall back to 'gpt-5.2' after stripping provider prefix and modifier"
    );
}

#[test]
fn test_load_cache_handles_corruption() {
    let temp = tempdir().unwrap();
    let aico_dir = temp.path().join("aico");
    fs::create_dir_all(&aico_dir).unwrap();
    let path = aico_dir.join("models.json");

    // Test 1: Invalid JSON syntax
    fs::write(&path, "invalid json {").unwrap();
    assert!(get_model_info_at("any-model", path.clone()).is_none());

    // Test 2: Valid JSON but wrong data types (Schema mismatch)
    fs::write(&path, r#"{"last_fetched": 123, "models": []}"#).unwrap();
    assert!(get_model_info_at("any-model", path.clone()).is_none());

    // Test 3: Missing required fields
    fs::write(&path, r#"{"models": {}}"#).unwrap();
    assert!(get_model_info_at("any-model", path.clone()).is_none());
}

#[tokio::test]
async fn test_model_registry_sync_logic() {
    let mut server = Server::new_async().await;
    let temp = tempdir().unwrap();
    let cache_dir = temp.path().to_path_buf();
    let cache_path = cache_dir.join("models.json");

    let lite_body =
        json!({"lite-model": {"max_input_tokens": 100}, "shared": {"max_input_tokens": 1}});
    let or_body = json!({"data": [{"id": "or-model", "context_length": 200, "pricing": {"prompt": "0.1", "completion": "0.2"}}, {"id": "shared", "context_length": 2, "pricing": {"prompt": "0", "completion": "0"}}]});

    let _m1 = server
        .mock("GET", "/lite")
        .with_body(lite_body.to_string())
        .create_async()
        .await;
    let _m2 = server
        .mock("GET", "/or")
        .with_body(or_body.to_string())
        .create_async()
        .await;

    unsafe {
        std::env::set_var("AICO_LITELLM_URL", format!("{}/lite", server.url()));
        std::env::set_var("AICO_OPENROUTER_URL", format!("{}/or", server.url()));
        std::env::set_var("AICO_CACHE_DIR", cache_dir.to_string_lossy().to_string());
    }

    // Trigger sync via get_model_info logic
    // We expect this to populate models.json in cache_dir.
    let _ = aico::model_registry::get_model_info("shared").await;

    let shared = get_model_info_at("shared", cache_path.clone())
        .expect("Cache file should exist and contain 'shared'");
    assert_eq!(shared.max_input_tokens, Some(2)); // OpenRouter priority
    assert_eq!(
        get_model_info_at("lite-model", cache_path.clone())
            .unwrap()
            .max_input_tokens,
        Some(100)
    );
    assert_eq!(
        get_model_info_at("or-model", cache_path)
            .unwrap()
            .max_input_tokens,
        Some(200)
    );
}
