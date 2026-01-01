use crate::exceptions::AicoError;
use crate::trust;
use std::env;
use std::path::PathBuf;

pub fn run(path: Option<PathBuf>, revoke: bool, show_list: bool) -> Result<(), AicoError> {
    if show_list {
        let projects = trust::list_trusted_projects();
        if projects.is_empty() {
            println!("No projects are currently trusted.");
        } else {
            println!("Trusted projects:");
            for p in projects {
                println!("  - {}", p);
            }
        }
        return Ok(());
    }

    let target_path = match path {
        Some(p) => p,
        None => env::current_dir()?,
    };

    if revoke {
        if trust::untrust_project(&target_path)? {
            println!("Revoked trust for: {}", target_path.display());
        } else {
            println!("Path was not trusted: {}", target_path.display());
        }
    } else {
        trust::trust_project(&target_path)?;
        println!("Success: Trusted project: {}", target_path.display());
        println!("Local addons in .aico/addons/ will now be loaded.");
    }

    Ok(())
}
