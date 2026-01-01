mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use common::init_session_with_history;
use predicates::prelude::*;

#[test]
fn test_dump_history_exports_active_window() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with two pairs
    init_session_with_history(
        root,
        vec![
            ("prompt zero", "response zero"),
            ("prompt one", "response one"),
        ],
    );

    // AND the first pair is excluded
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["undo", "0"])
        .assert()
        .success();

    // WHEN dump-history is run
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("dump-history")
        .assert()
        .success()
        // THEN it contains only the second pair with the correct role comments
        .stdout(predicate::str::contains(
            "<!-- llm-role: user -->\nprompt one",
        ))
        .stdout(predicate::str::contains(
            "<!-- llm-role: assistant -->\nresponse one",
        ))
        .stdout(predicate::str::contains("prompt zero").not())
        .stdout(predicate::str::contains("\n\n")); // Verify separator
}
