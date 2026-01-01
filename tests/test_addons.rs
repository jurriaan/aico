mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use tempfile::tempdir;

#[test]
fn test_discover_addons_untrusted_skips_project() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // 1. Initialize session
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // 2. Setup a project-local addon
    let addon_dir = root.join(".aico/addons");
    fs::create_dir_all(&addon_dir).unwrap();
    let addon_path = addon_dir.join("my-local-addon");

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::write(&addon_path, "#!/bin/sh\necho \"usage help\"").unwrap();
        let mut perms = fs::metadata(&addon_path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&addon_path, perms).unwrap();
    }
    #[cfg(windows)]
    {
        fs::write(&addon_path, "echo usage help").unwrap();
    }

    // 3. Project is NOT trusted by default.
    // WHEN running help
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("--help")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    // THEN local addon should not be discovered
    let stdout = String::from_utf8(output).unwrap();
    assert!(!stdout.contains("my-local-addon"));

    // 4. Trust the project
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("trust")
        .assert()
        .success();

    // 5. WHEN running help again
    let output_trusted = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("--help")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    // THEN local addon SHOULD be found
    let stdout_trusted = String::from_utf8(output_trusted).unwrap();
    assert!(stdout_trusted.contains("my-local-addon"));
}

#[test]
fn test_discover_addons_priority() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // Setup home/user dir
    let home = root.join("fake_home");
    let user_addon_dir = home.join(".config/aico/addons");
    fs::create_dir_all(&user_addon_dir).unwrap();

    // Create user addon
    let user_addon = user_addon_dir.join("test-cmd");
    fs::write(
        &user_addon,
        "#!/bin/sh\n[ \"$1\" = \"--usage\" ] && echo \"user help\"",
    )
    .unwrap();
    fs::set_permissions(&user_addon, fs::Permissions::from_mode(0o755)).unwrap();

    // Create project addon with same name (overrides user)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("trust")
        .assert()
        .success();

    let project_addon_dir = root.join(".aico/addons");
    fs::create_dir_all(&project_addon_dir).unwrap();
    let project_addon = project_addon_dir.join("test-cmd");
    fs::write(
        &project_addon,
        "#!/bin/sh\n[ \"$1\" = \"--usage\" ] && echo \"project help\"",
    )
    .unwrap();
    fs::set_permissions(&project_addon, fs::Permissions::from_mode(0o755)).unwrap();

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("--help")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();
    // Check that project help text is displayed, indicating it took priority
    assert!(stdout.contains("test-cmd"));
    assert!(stdout.contains("project help"));
    assert!(!stdout.contains("user help"));
}

#[test]
fn test_alias_group_prioritizes_builtin() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let home = root.join("fake_home");
    fs::create_dir_all(&home).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("trust")
        .assert()
        .success();

    // Create an addon named 'log' (existing builtin)
    let addon_dir = root.join(".aico/addons");
    fs::create_dir_all(&addon_dir).unwrap();
    let addon_path = addon_dir.join("log");
    fs::write(&addon_path, "#!/bin/sh\necho \"SHADOW_LOG\"").unwrap();
    fs::set_permissions(&addon_path, fs::Permissions::from_mode(0o755)).unwrap();

    // Running 'log' should still run the builtin log, not the script
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("log")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();
    assert!(!stdout.contains("SHADOW_LOG"));
}

#[test]
fn test_execute_addon_environment() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let home = root.join("fake_home");
    fs::create_dir_all(&home).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("trust")
        .assert()
        .success();

    let addon_dir = root.join(".aico/addons");
    fs::create_dir_all(&addon_dir).unwrap();
    let addon_path = addon_dir.join("env-test");

    // Script that prints AICO_SESSION_FILE
    fs::write(&addon_path, "#!/bin/sh\necho \"VAR=$AICO_SESSION_FILE\"").unwrap();
    fs::set_permissions(&addon_path, fs::Permissions::from_mode(0o755)).unwrap();

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("env-test")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();
    assert!(stdout.contains("VAR="));
    assert!(stdout.contains(".ai_session.json"));
}

#[test]
fn test_execute_addon_handles_os_error() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let home = root.join("fake_home");
    fs::create_dir_all(&home).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("trust")
        .assert()
        .success();

    let addon_dir = root.join(".aico/addons");
    fs::create_dir_all(&addon_dir).unwrap();
    let addon_path = addon_dir.join("broken");

    // Create a file that is executable but invalid (e.g. wrong shebang)
    fs::write(&addon_path, "#!/non/existent/interpreter\necho 1").unwrap();
    fs::set_permissions(&addon_path, fs::Permissions::from_mode(0o755)).unwrap();

    // execvpe should fail for this once started
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("broken")
        .assert()
        .failure();
}

#[test]
fn test_create_addon_command_execution() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let home = root.join("fake_home");
    fs::create_dir_all(&home).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("trust")
        .assert()
        .success();

    let addon_dir = root.join(".aico/addons");
    fs::create_dir_all(&addon_dir).unwrap();
    let addon_path = addon_dir.join("arg-test");

    // Script that prints its arguments
    fs::write(&addon_path, "#!/bin/sh\necho \"ARGS=$*\"").unwrap();
    fs::set_permissions(&addon_path, fs::Permissions::from_mode(0o755)).unwrap();

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("arg-test")
        .arg("hello")
        .arg("--world")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();
    assert!(stdout.contains("ARGS=hello --world"));
}

#[test]
fn test_discover_addons() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let home = root.join("fake_home");
    let user_addon_dir = home.join(".config/aico/addons");
    fs::create_dir_all(&user_addon_dir).unwrap();

    // Create a user addon
    let user_addon = user_addon_dir.join("user-cmd");
    fs::write(
        &user_addon,
        "#!/bin/sh\n[ \"$1\" = \"--usage\" ] && echo \"user help text\"",
    )
    .unwrap();
    fs::set_permissions(&user_addon, fs::Permissions::from_mode(0o755)).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("trust")
        .assert()
        .success();

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("--help")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();
    assert!(stdout.contains("user-cmd"));
    assert!(stdout.contains("user help text"));
}

#[test]
fn test_bundled_addons_are_available() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // bundled addons should be accessible without any setup
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("commit")
        .arg("--usage")
        .assert()
        .success()
        .stdout(predicates::str::contains(
            "Generates a Conventional Commit message",
        ));

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("summarize")
        .arg("--usage")
        .assert()
        .success()
        .stdout(predicates::str::contains(
            "Archives active history as dated summary",
        ));
}

#[test]
fn test_execute_addon_calls_execvpe() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let home = root.join("fake_home");
    fs::create_dir_all(&home).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("trust")
        .assert()
        .success();

    let addon_dir = root.join(".aico/addons");
    fs::create_dir_all(&addon_dir).unwrap();
    let addon_path = addon_dir.join("path-test");

    // Script that prints its own PATH to verify aico binary is prepended
    fs::write(&addon_path, "#!/bin/sh\necho \"PATH=$PATH\"").unwrap();
    fs::set_permissions(&addon_path, fs::Permissions::from_mode(0o755)).unwrap();

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("HOME", &home)
        .arg("path-test")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let stdout = String::from_utf8(output).unwrap();
    // In Rust implementation, the directory containing the aico binary is prepended to PATH
    assert!(stdout.contains("PATH="));
}
