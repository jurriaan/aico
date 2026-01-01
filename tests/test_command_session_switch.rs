use assert_cmd::cargo_bin_cmd;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_session_switch_switches_active_pointer() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a shared-history project with a second session
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-new", "feature"])
        .assert()
        .success();

    // WHEN I switch back to main
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-switch", "main"])
        .assert()
        .success();

    // THEN the pointer updates
    let pointer_path = root.join(".ai_session.json");
    let pointer_content = fs::read_to_string(pointer_path).unwrap();
    assert!(pointer_content.contains(".aico/sessions/main.json"));

    // WHEN I switch to feature again
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-switch", "feature"])
        .assert()
        .success();
    let pointer_content_after = fs::read_to_string(root.join(".ai_session.json")).unwrap();
    assert!(pointer_content_after.contains(".aico/sessions/feature.json"));
}

#[test]
fn test_session_switch_fails_for_missing_view() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a project with only default view
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // WHEN I try to switch to a non-existent view
    let cmd = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-switch", "nope"])
        .assert()
        .failure();

    // THEN the command fails with a clear error
    let stderr = String::from_utf8(cmd.get_output().stderr.clone()).unwrap();
    assert!(stderr.contains("Session view 'nope' not found"));
}
