use crate::exceptions::AicoError;
use crate::fs::atomic_write_text;
use crate::models::{AddonInfo, AddonSource};
use crate::session::find_session_file;
use crate::trust::is_project_trusted;
use std::collections::HashMap;
use std::env;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const PROJECT_ADDONS_DIR: &str = ".aico/addons";

// Macro to embed bundled addons
macro_rules! bundle_addon {
    ($name:expr, $path:expr) => {
        ($name, include_bytes!($path) as &'static [u8])
    };
}

fn get_cache_dir() -> PathBuf {
    let dir = crate::utils::get_app_cache_dir().join("bundled_addons");
    let _ = fs::create_dir_all(&dir);
    dir
}

fn extract_bundled_addon(name: &str, content: &[u8]) -> Result<PathBuf, AicoError> {
    let cache_dir = get_cache_dir();
    let target = cache_dir.join(name);

    // Check if content matches to avoid unnecessary writes/chmod
    if target.exists()
        && let Ok(existing) = fs::read(&target)
        && existing == content
    {
        return Ok(target);
    }

    atomic_write_text(&target, &String::from_utf8_lossy(content))?;

    let mut perms = fs::metadata(&target)?.permissions();
    perms.set_mode(0o755);
    fs::set_permissions(&target, perms)?;

    Ok(target)
}

fn run_usage(path: &Path) -> String {
    let output = Command::new(path)
        .arg("--usage")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output();

    match output {
        Ok(out) if out.status.success() => {
            let s = String::from_utf8_lossy(&out.stdout);
            s.lines().next().unwrap_or("").trim().to_string()
        }
        _ => String::new(),
    }
}

pub fn discover_addons() -> Vec<AddonInfo> {
    let mut candidates = Vec::new();

    // 1. Project Addons
    if let Some(session_path) = find_session_file() {
        let root = session_path.parent().unwrap_or(Path::new("."));
        let addon_dir = root.join(PROJECT_ADDONS_DIR);
        if addon_dir.is_dir() {
            if is_project_trusted(root) {
                if let Ok(entries) = fs::read_dir(addon_dir) {
                    for entry in entries.flatten() {
                        let path = entry.path();
                        if is_executable_file(&path) {
                            candidates.push((path, AddonSource::Project));
                        }
                    }
                }
            } else {
                eprintln!("[WARN] Project addons found but ignored. Run 'aico trust' to enable.");
            }
        }
    }

    // 2. User Addons
    let user_addon_dir = crate::utils::get_app_config_dir().join("addons");
    if let Ok(entries) = fs::read_dir(user_addon_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if is_executable_file(&path) {
                candidates.push((path, AddonSource::User));
            }
        }
    }

    // 3. Bundled Addons
    let bundled = vec![
        bundle_addon!("commit", "../.aico/addons/commit"),
        bundle_addon!("manage-context", "../.aico/addons/manage-context"),
        bundle_addon!("refine", "../.aico/addons/refine"),
        bundle_addon!("summarize", "../.aico/addons/summarize"),
    ];

    for (name, content) in bundled {
        if let Ok(path) = extract_bundled_addon(name, content) {
            candidates.push((path, AddonSource::Bundled));
        }
    }

    // 4. Process sequentially
    let mut results = HashMap::<String, AddonInfo>::new();

    for (path, source) in candidates {
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_string();
        if name.is_empty() {
            continue;
        }

        let help_text = run_usage(&path);
        let info = AddonInfo {
            name: name.clone(),
            path,
            help_text,
            source,
        };

        // Higher precedence for Project > User > Bundled
        if let Some(existing) = results.get(&name) {
            if info.source < existing.source {
                results.insert(name, info);
            }
        } else {
            results.insert(name, info);
        }
    }

    let mut list: Vec<AddonInfo> = results.into_values().collect();
    list.sort_by(|a, b| a.name.cmp(&b.name));
    list
}

fn is_executable_file(path: &Path) -> bool {
    if let Ok(meta) = fs::metadata(path) {
        if !meta.is_file() {
            return false;
        }

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            return meta.permissions().mode() & 0o111 != 0;
        }
    }
    false
}

pub fn execute_addon(addon: &AddonInfo, args: Vec<String>) -> Result<(), AicoError> {
    use std::os::unix::process::CommandExt;

    let mut cmd = Command::new(&addon.path);
    cmd.args(args);

    if let Some(session_file) = find_session_file()
        && let Ok(abs) = fs::canonicalize(session_file)
    {
        cmd.env("AICO_SESSION_FILE", abs);
    }

    // Prepend current aico binary location to PATH so scripts can call it
    if let Ok(current_exe) = env::current_exe()
        && let Some(bin_dir) = current_exe.parent()
    {
        let existing_path = env::var_os("PATH");

        let mut paths = match existing_path {
            Some(p) => env::split_paths(&p).collect::<Vec<_>>(),
            None => Vec::new(),
        };

        paths.insert(0, bin_dir.to_path_buf());

        if let Ok(new_path) = env::join_paths(paths) {
            cmd.env("PATH", new_path);
        }
    }

    // Replace current process with addon
    let err = cmd.exec();
    Err(AicoError::Io(err))
}
