mod common;
use assert_cmd::cargo_bin_cmd;
use predicates::prelude::*;
use std::fs;
use tempfile;
use tempfile::tempdir;

#[test]
fn test_add_file_to_context() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // Init
    let mut cmd = cargo_bin_cmd!("aico");
    cmd.current_dir(root).arg("init").assert().success();

    // Create file
    let file_path = root.join("test_file.py");
    fs::write(&file_path, "print('hello')").unwrap();

    // Add
    let mut cmd_add = cargo_bin_cmd!("aico");
    cmd_add
        .current_dir(root)
        .arg("add")
        .arg("test_file.py")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Added file to context: test_file.py",
        ));

    // Verify View
    let view_path = root.join(".aico/sessions/main.json");
    let content = fs::read_to_string(view_path).unwrap();
    assert!(content.contains("test_file.py"));
}

#[test]
fn test_add_duplicate_file_is_ignored() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    fs::write(root.join("test.py"), "").unwrap();

    // Add once
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "test.py"])
        .assert()
        .success();

    // Add again
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "test.py"])
        .assert()
        .success()
        .stdout(predicate::str::contains("File already in context: test.py"));
}

#[test]
fn test_add_non_existent_file_fails() {
    let temp = tempfile::tempdir().unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(&temp)
        .arg("init")
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(&temp)
        .args(["add", "missing.py"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("Error: File not found"));
}

#[test]
fn test_drop_single_file_successfully() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    fs::write(root.join("f1.py"), "").unwrap();
    fs::write(root.join("f2.py"), "").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "f1.py", "f2.py"])
        .assert()
        .success();

    // Drop
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["drop", "f1.py"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Dropped file from context: f1.py"));

    // Verify f2 remains
    let content = fs::read_to_string(root.join(".aico/sessions/main.json")).unwrap();
    assert!(!content.contains("f1.py"));
    assert!(content.contains("f2.py"));
}

#[test]
fn test_add_multiple_files_successfully() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    fs::write(root.join("file1.py"), "").unwrap();
    fs::write(root.join("file2.py"), "").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file1.py", "file2.py"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Added file to context: file1.py"))
        .stdout(predicate::str::contains("Added file to context: file2.py"));

    let content = fs::read_to_string(root.join(".aico/sessions/main.json")).unwrap();
    assert!(content.contains("file1.py"));
    assert!(content.contains("file2.py"));
}

#[test]
fn test_add_multiple_files_with_one_already_in_context() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    fs::write(root.join("file1.py"), "").unwrap();
    fs::write(root.join("file2.py"), "").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file1.py"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file1.py", "file2.py"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "File already in context: file1.py",
        ))
        .stdout(predicate::str::contains("Added file to context: file2.py"));
}

#[test]
fn test_add_multiple_files_with_one_non_existent_partially_fails() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    fs::write(root.join("valid.py"), "").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "valid.py", "missing.py"])
        .assert()
        .failure()
        .stdout(predicate::str::contains("Added file to context: valid.py"))
        .stderr(predicate::str::contains(
            "Error: File not found: missing.py",
        ));

    // Verify valid.py WAS still added despite the error
    let content = fs::read_to_string(root.join(".aico/sessions/main.json")).unwrap();
    assert!(content.contains("valid.py"));
}

#[test]
fn test_drop_multiple_files_successfully() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    fs::write(root.join("f1.py"), "").unwrap();
    fs::write(root.join("f2.py"), "").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "f1.py", "f2.py"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["drop", "f1.py", "f2.py"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Dropped file from context: f1.py"))
        .stdout(predicate::str::contains("Dropped file from context: f2.py"));
}

#[test]
fn test_drop_multiple_with_one_not_in_context_partially_fails() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    fs::write(root.join("f1.py"), "").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "f1.py"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["drop", "f1.py", "missing.py"])
        .assert()
        .failure()
        .stdout(predicate::str::contains("Dropped file from context: f1.py"))
        .stderr(predicate::str::contains(
            "Error: File not in context: missing.py",
        ));
}

#[test]
fn test_add_symlink_to_inside_success() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    let target = root.join("target.py");
    fs::write(&target, "print(1)").unwrap();
    let link = root.join("link.py");
    std::os::unix::fs::symlink("target.py", &link).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "link.py"])
        .assert()
        .success()
        .stdout(predicate::str::contains("Added file to context: link.py"));
}

#[test]
fn test_drop_symlink_success() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    fs::write(root.join("target.py"), "").unwrap();
    std::os::unix::fs::symlink("target.py", root.join("link.py")).unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "link.py"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["drop", "link.py"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Dropped file from context: link.py",
        ));
}

#[test]
fn test_drop_file_not_in_context_fails() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    fs::write(root.join("f1.py"), "").unwrap();

    // Attempt to drop file not in context (file exists on disk)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["drop", "f1.py"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Error: File not in context: f1.py",
        ));
}

#[test]
fn test_drop_file_missing_from_disk_but_in_context_success() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    let f = root.join("transient.py");
    fs::write(&f, "").unwrap();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "transient.py"])
        .assert()
        .success();

    // Delete from disk
    fs::remove_file(&f).unwrap();

    // Drop should still work because it removes from metadata
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["drop", "transient.py"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Dropped file from context: transient.py",
        ));

    let content = fs::read_to_string(root.join(".aico/sessions/main.json")).unwrap();
    assert!(!content.contains("transient.py"));
}

#[test]
fn test_drop_autocompletion() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // Init session
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // Create and add files
    fs::write(root.join("file1.txt"), "content").unwrap();
    fs::write(root.join("file2.txt"), "content").unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("add")
        .arg("file1.txt")
        .arg("file2.txt")
        .assert()
        .success();

    // Verify 'drop' suggests context files using clap's dynamic completion
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("COMPLETE", "bash")
        .env("_CLAP_COMPLETE_INDEX", "2")
        .args(["--", "aico", "drop", "file"])
        .assert()
        .stdout(predicate::str::contains("file1.txt"))
        .stdout(predicate::str::contains("file2.txt"));
}

#[test]
fn test_autocompletion_includes_symlinks() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    let target = root.join("real_file.txt");
    fs::write(&target, "data").unwrap();

    #[cfg(unix)]
    {
        let link = root.join("link_file.txt");
        std::os::unix::fs::symlink("real_file.txt", &link).unwrap();

        cargo_bin_cmd!("aico")
            .current_dir(root)
            .arg("add")
            .arg("link_file.txt")
            .assert()
            .success();

        let session = aico::session::Session::load(root.join(".ai_session.json")).unwrap();
        let context = session.get_context_files();

        // Must preserve the link name, not resolve to target
        assert!(context.contains(&"link_file.txt".to_string()));
        assert!(!context.contains(&"real_file.txt".to_string()));
    }
}

#[test]
fn test_drop_is_silent_on_missing_files() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["init", "--model", "test-model"])
        .assert()
        .success();

    // GIVEN a file tagged in context but missing from disk
    let view_path = root.join(".aico/sessions/main.json");
    let mut view: aico::models::SessionView =
        serde_json::from_str(&fs::read_to_string(&view_path).unwrap()).unwrap();
    view.context_files.push("missing.py".to_string());
    fs::write(&view_path, serde_json::to_string(&view).unwrap()).unwrap();

    // WHEN dropping it
    let assert = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["drop", "missing.py"])
        .assert()
        .success();

    // THEN it should NOT emit the "not found on disk" warning to stderr
    assert
        .stderr(predicate::str::contains("Warning: Context files not found on disk").not())
        .stdout(predicate::str::contains(
            "Dropped file from context: missing.py",
        ));
}
