use crate::exceptions::AicoError;
use std::fs;
use std::io::Write;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use tempfile::NamedTempFile;

/// Atomically write text to a file using a temporary file + rename strategy.
pub fn atomic_write_text<P: AsRef<Path>>(path: P, text: &str) -> Result<(), AicoError> {
    let path = path.as_ref();
    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(dir)?;

    // Create temp file in the same directory to ensure atomic rename works across filesystems
    let mut temp_file = NamedTempFile::new_in(dir)?;

    temp_file.write_all(text.as_bytes())?;

    // Persist replaces the destination path atomically
    temp_file
        .persist(path)
        .map_err(|e| AicoError::Io(e.error))?;

    Ok(())
}

/// Validates input paths relative to session root.
pub fn validate_input_paths(
    session_root: &Path,
    file_paths: &[PathBuf],
    require_exists: bool,
) -> (Vec<String>, bool) {
    let mut valid_rels = Vec::new();
    let mut has_errors = false;

    let root_canon = match fs::canonicalize(session_root) {
        Ok(p) => p,
        Err(_) => return (vec![], true),
    };

    for path in file_paths {
        // 1. Resolve to logical absolute path preserving symlinks segments where possible
        let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let logical_abs_path = normalize_path(&cwd.join(path));

        // 2. Existence check (optional but standard)
        if require_exists {
            if !logical_abs_path.exists() {
                eprintln!("Error: File not found: {}", path.display());
                has_errors = true;
                continue;
            }
            if logical_abs_path.is_dir() {
                eprintln!("Error: Cannot add a directory: {}", path.display());
                has_errors = true;
                continue;
            }
        }

        // 3. Security check: Must be inside session root physically.
        // We canonicalize the final target to ensure symlinks aren't escaping the root.
        let physical_target = match fs::canonicalize(&logical_abs_path) {
            Ok(p) => p,
            Err(_) if !require_exists => logical_abs_path.clone(), // Non-existent file target
            Err(_) => {
                eprintln!("Error: Could not resolve path: {}", path.display());
                has_errors = true;
                continue;
            }
        };

        if !physical_target.starts_with(&root_canon) {
            eprintln!(
                "Error: File '{}' is outside the session root",
                path.display()
            );
            has_errors = true;
            continue;
        }

        // 4. Calculate relative path using the LOGICAL path to preserve symlink semantics in the context structure.
        match logical_abs_path.strip_prefix(session_root) {
            Ok(rel) => {
                let rel_str = rel.to_string_lossy().replace('\\', "/");
                valid_rels.push(rel_str);
            }
            Err(_) => {
                // If the logical path doesn't start with root (e.g. symlink into root from outside),
                // we use the physical relative path as the context identifier.
                if let Ok(rel) = physical_target.strip_prefix(&root_canon) {
                    let rel_str = rel.to_string_lossy().replace('\\', "/");
                    valid_rels.push(rel_str);
                } else {
                    eprintln!(
                        "Error: File '{}' is logically outside the session root",
                        path.display()
                    );
                    has_errors = true;
                }
            }
        }
    }

    (valid_rels, has_errors)
}

/// Simple path normalization (like python os.path.normpath)
fn normalize_path(path: &Path) -> PathBuf {
    let components = path.components().peekable();
    let mut ret = PathBuf::new();

    for component in components {
        match component {
            Component::Prefix(..) => {
                ret.push(component.as_os_str());
            }
            Component::RootDir => {
                ret.push(component.as_os_str());
            }
            Component::CurDir => {}
            Component::ParentDir => {
                ret.pop();
            }
            Component::Normal(c) => {
                ret.push(c);
            }
        }
    }
    ret
}
