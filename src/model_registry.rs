use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

const CACHE_TTL_DAYS: i64 = 14;

fn get_litellm_url() -> String {
    env::var("AICO_LITELLM_URL").unwrap_or_else(|_| {
        "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
            .to_string()
    })
}

fn get_openrouter_url() -> String {
    env::var("AICO_OPENROUTER_URL")
        .unwrap_or_else(|_| "https://openrouter.ai/api/v1/models".to_string())
}

#[derive(Debug, Serialize, Deserialize)]
struct ModelRegistry {
    last_fetched: String,
    models: HashMap<String, ModelInfo>,
}

#[derive(Deserialize)]
struct OpenRouterPricing {
    prompt: String,
    completion: String,
}

#[derive(Deserialize)]
struct OpenRouterItem {
    id: String,
    context_length: u32,
    pricing: OpenRouterPricing,
}

#[derive(Deserialize)]
struct OpenRouterResponse {
    data: Vec<OpenRouterItem>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelInfo {
    pub max_input_tokens: Option<u32>,
    pub input_cost_per_token: Option<f64>,
    pub output_cost_per_token: Option<f64>,
}

fn get_cache_path() -> PathBuf {
    if let Ok(custom) = env::var("AICO_CACHE_DIR") {
        return PathBuf::from(custom).join("models.json");
    }
    let xdg = env::var("XDG_CACHE_HOME").map(PathBuf::from).ok();
    let home = env::var("HOME").map(PathBuf::from).ok();

    let base = xdg
        .or_else(|| home.map(|h| h.join(".cache")))
        .unwrap_or_else(|| PathBuf::from("."));
    base.join("aico").join("models.json")
}

static REGISTRY_CACHE: std::sync::OnceLock<ModelRegistry> = std::sync::OnceLock::new();

pub async fn get_model_info(model_id: &str) -> Option<ModelInfo> {
    if let Some(registry) = REGISTRY_CACHE.get() {
        return get_info_from_registry(model_id, registry);
    }

    let path = get_cache_path();
    if let Some(registry) = ensure_cache(&path).await {
        let _ = REGISTRY_CACHE.set(registry);
    }

    if let Some(registry) = REGISTRY_CACHE.get() {
        return get_info_from_registry(model_id, registry);
    }
    None
}

async fn ensure_cache(path: &PathBuf) -> Option<ModelRegistry> {
    let mut should_fetch = false;
    let existing: Option<ModelRegistry> = if path.exists() {
        fs::read_to_string(path).ok().and_then(|c| {
            let reg: Option<ModelRegistry> = serde_json::from_str(&c).ok();
            if let Some(ref r) = reg
                && let Ok(dt) = DateTime::parse_from_rfc3339(&r.last_fetched)
                && (Utc::now() - dt.with_timezone(&Utc)).num_days() < CACHE_TTL_DAYS
            {
                return reg;
            }
            should_fetch = true;
            reg
        })
    } else {
        should_fetch = true;
        None
    };

    if should_fetch {
        let _ = update_registry(path.clone()).await;
        // Re-read after potential update
        fs::read_to_string(path)
            .ok()
            .and_then(|c| serde_json::from_str(&c).ok())
    } else {
        existing
    }
}

async fn update_registry(path: PathBuf) -> Result<(), Box<dyn std::error::Error>> {
    crate::utils::setup_crypto_provider();

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()?;
    let mut all_models: HashMap<String, ModelInfo> = HashMap::new();

    if let Ok(resp) = client.get(get_litellm_url()).send().await
        && let Ok(lite) = resp.json::<HashMap<String, ModelInfo>>().await
    {
        all_models.extend(lite);
    }
    if let Ok(resp) = client.get(get_openrouter_url()).send().await
        && let Ok(or) = resp.json::<OpenRouterResponse>().await
    {
        for item in or.data {
            all_models.insert(
                item.id,
                ModelInfo {
                    max_input_tokens: Some(item.context_length),
                    input_cost_per_token: item.pricing.prompt.parse().ok(),
                    output_cost_per_token: item.pricing.completion.parse().ok(),
                },
            );
        }
    }

    if all_models.is_empty() {
        return Ok(());
    }

    let registry = ModelRegistry {
        last_fetched: Utc::now().to_rfc3339(),
        models: all_models,
    };

    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let json = serde_json::to_string_pretty(&registry)?;
    crate::fs::atomic_write_text(path, &json)?;

    Ok(())
}

fn get_info_from_registry(model_id: &str, registry: &ModelRegistry) -> Option<ModelInfo> {
    // Pre-process: Strip any flags (everything after first +)
    let base_model = model_id.split('+').next().unwrap_or(model_id);

    // 1. Exact Match
    if let Some(info) = registry.models.get(base_model) {
        return Some(info.clone());
    }

    // 2. Strip Provider Prefix (openai/gpt-4 -> gpt-4)
    if let Some((_, stripped)) = base_model.split_once('/') {
        if let Some(info) = registry.models.get(stripped) {
            return Some(info.clone());
        }

        // 3. Strip Vendor (google/gemini -> gemini)
        if let Some((_, bare)) = stripped.split_once('/')
            && let Some(info) = registry.models.get(bare)
        {
            return Some(info.clone());
        }
    }

    None
}

pub fn get_model_info_at(model_id: &str, path: PathBuf) -> Option<ModelInfo> {
    if !path.exists() {
        return None;
    }

    let content = fs::read_to_string(path).ok()?;
    let registry: ModelRegistry = serde_json::from_str(&content).ok()?;
    get_info_from_registry(model_id, &registry)
}
