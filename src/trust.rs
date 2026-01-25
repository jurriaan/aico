use crate::exceptions::AicoError;
use crate::fs::atomic_write_json;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Default)]
struct TrustConfig {
    trusted_projects: Vec<String>,
}

pub fn get_trust_file() -> PathBuf {
    crate::utils::get_app_config_dir().join("trust.json")
}

fn load_trusted_paths() -> HashSet<String> {
    let trust_file = get_trust_file();
    if !trust_file.exists() {
        return HashSet::new();
    }

    match crate::fs::read_json::<TrustConfig>(&trust_file) {
        Ok(config) => config.trusted_projects.into_iter().collect(),
        Err(_) => HashSet::new(),
    }
}

fn save_trusted_paths(paths: HashSet<String>) -> Result<(), AicoError> {
    let trust_file = get_trust_file();
    if let Some(parent) = trust_file.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut vec_paths: Vec<String> = paths.into_iter().collect();
    vec_paths.sort();

    let config = TrustConfig {
        trusted_projects: vec_paths,
    };

    atomic_write_json(&trust_file, &config)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(&trust_file) {
            let mut perms = meta.permissions();
            perms.set_mode(0o600);
            let _ = fs::set_permissions(&trust_file, perms);
        }
    }

    Ok(())
}

pub fn is_project_trusted(path: &Path) -> bool {
    let resolved = match fs::canonicalize(path) {
        Ok(p) => p.to_string_lossy().to_string(),
        Err(_) => return false,
    };
    let trusted = load_trusted_paths();
    trusted.contains(&resolved)
}

pub fn trust_project(path: &Path) -> Result<(), AicoError> {
    let resolved = fs::canonicalize(path)?;
    let resolved_str = resolved.to_string_lossy().to_string();
    let mut trusted = load_trusted_paths();
    trusted.insert(resolved_str);
    save_trusted_paths(trusted)
}

pub fn untrust_project(path: &Path) -> Result<bool, AicoError> {
    let resolved = fs::canonicalize(path)?;
    let resolved_str = resolved.to_string_lossy().to_string();
    let mut trusted = load_trusted_paths();
    let removed = trusted.remove(&resolved_str);
    if removed {
        save_trusted_paths(trusted)?;
    }
    Ok(removed)
}

pub fn list_trusted_projects() -> Vec<String> {
    let mut list: Vec<String> = load_trusted_paths().into_iter().collect();
    list.sort();
    list
}
