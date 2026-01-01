use assert_cmd::cargo::cargo_bin_cmd;
use predicates::prelude::*;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_trust_list_empty_state() {
    let temp = tempdir().unwrap();
    let config_dir = temp.path().join(".config");

    // WHEN running trust --list on a fresh system
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--list"])
        .assert()
        .success()
        // THEN it reports no projects are trusted
        .stdout(predicate::str::contains(
            "No projects are currently trusted.",
        ));
}

#[test]
fn test_trust_canonicalizes_paths() {
    let temp = tempdir().unwrap();
    let project_dir = temp.path().join("my_project");
    fs::create_dir_all(&project_dir).unwrap();
    let config_dir = temp.path().join(".config");

    // GIVEN a path with relative segments
    let relative_path = project_dir.join("..").join("my_project");

    // WHEN trusting that path
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .arg("trust")
        .arg(relative_path)
        .assert()
        .success();

    // THEN the canonical (absolute) path is listed
    let abs_path_str = fs::canonicalize(&project_dir)
        .unwrap()
        .to_string_lossy()
        .to_string();
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--list"])
        .assert()
        .success()
        .stdout(predicate::str::contains(abs_path_str));
}

#[test]
fn test_revoke_untrusted_path_reports_noop() {
    let temp = tempdir().unwrap();
    let project_dir = temp.path().join("not_trusted");
    fs::create_dir_all(&project_dir).unwrap();
    let config_dir = temp.path().join(".config");

    // WHEN revoking trust for a path that was never trusted
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--revoke"])
        .arg(&project_dir)
        .assert()
        .success()
        // THEN it informs the user the path was not trusted
        .stdout(predicate::str::contains("Path was not trusted"));
}

#[test]
fn test_trust_command_success_and_revoke_flow() {
    let temp = tempdir().unwrap();
    let project_path = temp.path().join("my-project");
    fs::create_dir_all(&project_path).unwrap();
    let config_dir = temp.path().join(".config");

    // 1. Trust the project
    cargo_bin_cmd!("aico")
        .current_dir(&project_path)
        .env("XDG_CONFIG_HOME", &config_dir)
        .arg("trust")
        .assert()
        .success()
        .stdout(predicate::str::contains("Success: Trusted project"));

    let trust_file = config_dir.join("aico/trust.json");
    assert!(trust_file.exists());

    // 2. Verify trust is listed
    let abs_path_str = fs::canonicalize(&project_path)
        .unwrap()
        .to_string_lossy()
        .to_string();
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--list"])
        .assert()
        .success()
        .stdout(predicate::str::contains(&abs_path_str));

    // 3. Revoke trust
    cargo_bin_cmd!("aico")
        .current_dir(&project_path)
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--revoke"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Revoked trust for"));

    // 4. Verify list is empty again
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--list"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "No projects are currently trusted",
        ));
}

#[test]
fn test_trust_command_cwd() {
    let temp = tempdir().unwrap();
    let project_dir = temp.path().join("project");
    fs::create_dir_all(&project_dir).unwrap();
    let config_dir = temp.path().join("config");

    cargo_bin_cmd!("aico")
        .current_dir(&project_dir)
        .env("XDG_CONFIG_HOME", &config_dir)
        .arg("trust")
        .assert()
        .success()
        .stdout(predicate::str::contains("Trusted project"));

    let abs_path = fs::canonicalize(&project_dir)
        .unwrap()
        .to_string_lossy()
        .to_string();
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--list"])
        .assert()
        .success()
        .stdout(predicate::str::contains(abs_path));
}

#[test]
fn test_trust_command_list() {
    let temp = tempdir().unwrap();
    let project_path = temp.path().join("trusted-project");
    fs::create_dir_all(&project_path).unwrap();
    let config_dir = temp.path().join(".config");

    // WHEN trusting a project
    cargo_bin_cmd!("aico")
        .current_dir(&project_path)
        .env("XDG_CONFIG_HOME", &config_dir)
        .arg("trust")
        .assert()
        .success();

    // THEN --list contains the absolute path
    let abs_path_str = fs::canonicalize(&project_path)
        .unwrap()
        .to_string_lossy()
        .to_string();
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--list"])
        .assert()
        .success()
        .stdout(predicate::str::contains(&abs_path_str));
}

#[test]
fn test_trust_command_revoke() {
    let temp = tempdir().unwrap();
    let project_path = temp.path().join("revoked-project");
    fs::create_dir_all(&project_path).unwrap();
    let config_dir = temp.path().join(".config");

    // GIVEN a trusted project
    cargo_bin_cmd!("aico")
        .current_dir(&project_path)
        .env("XDG_CONFIG_HOME", &config_dir)
        .arg("trust")
        .assert()
        .success();

    // WHEN revoking trust
    cargo_bin_cmd!("aico")
        .current_dir(&project_path)
        .env("XDG_CONFIG_HOME", &config_dir)
        .arg("trust")
        .arg("--revoke")
        .assert()
        .success();

    // THEN --list is empty
    cargo_bin_cmd!("aico")
        .env("XDG_CONFIG_HOME", &config_dir)
        .args(["trust", "--list"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "No projects are currently trusted.",
        ));
}
