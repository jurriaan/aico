use std::fs;
use tempfile::tempdir;

#[test]
fn test_trust_flow() {
    let temp = tempdir().unwrap();
    // SETUP: Mock trust file location by setting XDG_CONFIG_HOME
    let config_dir = temp.path().join("config");
    unsafe {
        std::env::set_var("XDG_CONFIG_HOME", config_dir.to_str().unwrap());
    }

    let project_dir = temp.path().join("my-project");
    fs::create_dir_all(&project_dir).unwrap();
    let project_path = fs::canonicalize(&project_dir).unwrap();

    // 1. Default state: not trusted
    assert!(!aico::trust::is_project_trusted(&project_path));
    assert!(aico::trust::list_trusted_projects().is_empty());

    // 2. Trust project
    aico::trust::trust_project(&project_path).unwrap();
    assert!(aico::trust::is_project_trusted(&project_path));
    assert_eq!(
        aico::trust::list_trusted_projects(),
        vec![project_path.to_string_lossy().to_string()]
    );

    // 3. Verify file permissions (0o600) on Unix
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let trust_file = config_dir.join("aico").join("trust.json");
        let meta = fs::metadata(trust_file).unwrap();
        assert_eq!(meta.permissions().mode() & 0o777, 0o600);
    }

    // 4. Untrust project
    assert!(aico::trust::untrust_project(&project_path).unwrap());
    assert!(!aico::trust::is_project_trusted(&project_path));
    assert!(aico::trust::list_trusted_projects().is_empty());

    // 5. Untrust non-existent
    assert!(!aico::trust::untrust_project(&project_path).unwrap());
}
