use assert_cmd::cargo_bin_cmd;
use tempfile::tempdir;

#[test]
fn test_session_list_shows_active_and_all_views() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a shared-history project with one default view
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("init")
        .assert()
        .success();

    // WHEN I list sessions
    let output1 = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("session-list")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let stdout1 = String::from_utf8(output1).unwrap();

    // THEN it shows the default 'main' view as active
    assert!(stdout1.contains("Available sessions:"));
    assert!(stdout1.contains("  - main (active)"));

    // WHEN I create a new session and list again
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["session-new", "dev"])
        .assert()
        .success();

    let output2 = cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("session-list")
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let stdout2 = String::from_utf8(output2).unwrap();

    // THEN both sessions are listed and 'dev' is active
    assert!(stdout2.contains("  - main"));
    assert!(stdout2.contains("  - dev (active)"));
}
