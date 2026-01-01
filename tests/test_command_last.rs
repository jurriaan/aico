mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use common::{init_session_with_history, load_view, setup_session};
use predicates::prelude::*;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_last_can_select_pair_by_positive_index() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(
        root,
        vec![
            ("p0", "assistant response 0"),
            ("p1", "assistant response 1"),
        ],
    );

    // WHEN 'last 0' is run
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "0"])
        .assert()
        .success()
        .stdout(predicate::str::contains("assistant response 0"))
        .stdout(predicate::str::contains("assistant response 1").not());
}

#[test]
fn test_last_default_shows_last_assistant_response() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(
        root,
        vec![
            ("p0", "assistant response 0"),
            ("p1", "assistant response 1"),
        ],
    );

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .stdout(predicate::str::contains("assistant response 1"))
        .stdout(predicate::str::contains("assistant response 0").not());
}

#[test]
fn test_last_prompt_flag_shows_user_prompt() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("user prompt 0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--prompt"])
        .assert()
        .success()
        .stdout(predicate::str::contains("user prompt 0"));
}

#[test]
fn test_last_verbatim_flag_for_prompt() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    let raw_prompt = "# Title\n`code` content";
    init_session_with_history(root, vec![(raw_prompt, "r0")]);

    // WHEN running with --verbatim and --prompt
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--prompt", "--verbatim"])
        .assert()
        .success()
        // THEN the raw prompt content is printed exactly
        .stdout(predicate::eq(raw_prompt));
}

#[test]
fn test_last_json_output() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let json_str = String::from_utf8(output).unwrap();
    let json_data: serde_json::Value = serde_json::from_str(&json_str).unwrap();

    assert_eq!(json_data["pair_index"], 0);
    assert_eq!(json_data["user"]["content"], "p0");
    assert_eq!(json_data["assistant"]["content"], "r0");
    // Ensure IDs (global store indices) are present and correct
    assert_eq!(json_data["user"]["id"], 0);
    assert_eq!(json_data["assistant"]["id"], 1);
}

#[test]
fn test_last_recompute_for_diff_response() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with a diff in history but file has changed on disk
    let file_path = root.join("file.py");
    fs::write(&file_path, "new disk content\n").unwrap();

    let diff_response =
        "File: file.py\n<<<<<<< SEARCH\nold content\n=======\npatched content\n>>>>>>> REPLACE";
    init_session_with_history(root, vec![("rename", diff_response)]);

    // Update history to be Mode::Diff so --recompute knows to output only the diff
    let history_path = root.join(".aico/history/0.jsonl");
    let content = std::fs::read_to_string(&history_path).unwrap();
    let updated = content.replace("\"mode\":\"conversation\"", "\"mode\":\"diff\"");
    std::fs::write(&history_path, updated).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file.py"])
        .assert()
        .success();

    // WHEN running with --recompute
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--recompute"])
        .assert()
        .success()
        // THEN it should fail to apply because SEARCH (old content) doesn't match disk (new disk content)
        .stdout(predicate::str::is_empty())
        .stderr(predicate::str::contains("Warnings:"))
        .stderr(predicate::str::contains("could not be found in 'file.py'"));
}

#[test]
fn test_last_can_select_pair_by_negative_index() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // -2 should resolve to index 0 (the first pair)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "-2"])
        .assert()
        .success()
        .stdout(predicate::str::contains("r0"))
        .stdout(predicate::str::contains("r1").not());
}

#[test]
fn test_last_json_output_ignores_prompt_flag() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--json", "--prompt"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let json_data: serde_json::Value = serde_json::from_slice(&output).unwrap();
    assert!(json_data.get("user").is_some());
    assert!(json_data.get("assistant").is_some());
    assert_eq!(json_data["user"]["content"], "p0");
}

#[test]
fn test_last_json_output_with_specific_index() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "0", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let json_data: serde_json::Value = serde_json::from_slice(&output).unwrap();
    assert_eq!(json_data["pair_index"], 0);
    assert_eq!(json_data["assistant"]["content"], "r0");
}

#[test]
fn test_last_fails_when_no_pairs_exist() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    setup_session(root);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "No message pairs found in history",
        ));
}

#[test]
fn test_last_fails_with_invalid_index_format() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "abc"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Invalid index 'abc'. Must be an integer.",
        ));
}

#[test]
fn test_last_fails_with_out_of_bounds_index() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "5"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Index out of bounds. Valid indices are in the range 0 (or -1).",
        ));
}

#[test]
fn test_last_can_access_pair_before_active_window() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Move history pointer forward
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["set-history", "1"])
        .assert()
        .success();

    // Verify last can still see pair 0
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "0"])
        .assert()
        .success()
        .stdout(predicate::str::contains("r0"));
}

#[test]
fn test_last_can_access_pair_before_active_window_shared_history() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // Directly manipulate view to set history_start_pair
    let view_path = root.join(".aico/sessions/main.json");
    let mut view = load_view(root);
    view.history_start_pair = 1;
    let json = serde_json::to_string(&view).unwrap();
    std::fs::write(view_path, json).unwrap();

    // Verify last can still see pair 0 despite start pointer
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "0"])
        .assert()
        .success()
        .stdout(predicate::str::contains("r0"));
}

#[test]
fn test_last_recompute_fails_with_prompt_flag() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    init_session_with_history(root, vec![("p", "r")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--recompute", "--prompt"])
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "--recompute cannot be used with --prompt",
        ));
}

#[test]
fn test_last_is_composable_for_piping() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    let conversational_response = "Here is the fix:\nFile: fix.txt\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\nHope this helps!";

    // Create the file so the patch succeeds and produces a unified diff
    std::fs::write(root.join("fix.txt"), "old\n").unwrap();

    // Create session where Mode is Diff
    init_session_with_history(root, vec![("fix it", conversational_response)]);

    // Ensure the file is in context so the analyzer can find it
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "fix.txt"])
        .assert()
        .success();

    // Update the history record in the store to be Mode::Diff
    // (Our init helper makes them Conversation by default, but we need Mode::Diff for Composable logic)
    let history_path = root.join(".aico/history/0.jsonl");
    let content = std::fs::read_to_string(&history_path).unwrap();
    let updated = content.replace("\"mode\":\"conversation\"", "\"mode\":\"diff\"");
    std::fs::write(&history_path, updated).unwrap();

    // WHEN running aico last (which usually detects non-TTY in tests/assert_cmd)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        // THEN it outputs ONLY the diff, no conversational garbage
        .stdout(predicate::str::contains("--- a/fix.txt"))
        .stdout(predicate::str::contains("new"))
        .stdout(predicate::str::contains("Hope this helps").not())
        .stdout(predicate::str::contains("Here is the fix").not());
}

#[test]
fn test_last_piped_flexible_contract_for_ask_mode_with_diff() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    let conv_with_diff = "Plan:\nFile: a.txt\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE";
    fs::write(root.join("a.txt"), "old\n").unwrap();
    init_session_with_history(root, vec![("p0", conv_with_diff)]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "a.txt"])
        .assert()
        .success();

    // WHEN running aico last piped
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        // THEN it prefers the diff over the conversation text (Flexible Contract)
        .stdout(predicate::str::contains("--- a/a.txt"))
        .stdout(predicate::str::contains("Plan:").not());
}

#[test]
fn test_last_piped_flexible_contract_for_conversation_mode() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    let conv_text = "Standard conversation without diff.";
    init_session_with_history(root, vec![("p0", conv_text)]);

    // WHEN running aico last piped
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        // THEN it falls back to raw content
        .stdout(predicate::eq(conv_text));
}

#[test]
fn test_last_recompute_piped_promotes_diff_in_conversation_mode() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    let file_path = root.join("hello.py");
    fs::write(&file_path, "print('hello')\n").unwrap();

    // A conversational message that contains a diff block
    let response = "Sure, I can fix that.\n\nFile: hello.py\n<<<<<<< SEARCH\nprint('hello')\n=======\nprint('hi')\n>>>>>>> REPLACE\n\nHope that works!";

    init_session_with_history(root, vec![("Update greeting", response)]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "hello.py"])
        .assert()
        .success();

    // WHEN running aico last --recompute piped
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--recompute"])
        .assert()
        .success()
        // THEN it should output ONLY the unified diff (Flexible Contract promotion)
        .stdout(predicate::str::contains("--- a/hello.py"))
        .stdout(predicate::str::contains("+print('hi')"))
        .stdout(predicate::str::contains("Sure, I can fix that.").not())
        .stdout(predicate::str::contains("Hope that works!").not());
}

#[test]
fn test_last_piped_strict_contract_for_diff_mode_failure() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    let fail_patch = "I tried to fix it but the file was missing.\nFile: missing.py\n<<<<<<< SEARCH\n...\n>>>>>>> REPLACE";
    init_session_with_history(root, vec![("p0", fail_patch)]);

    // Force Mode to Diff
    let history_path = root.join(".aico/history/0.jsonl");
    let content = std::fs::read_to_string(&history_path).unwrap();
    let updated = content.replace("\"mode\":\"conversation\"", "\"mode\":\"diff\"");
    std::fs::write(&history_path, updated).unwrap();

    // WHEN running aico last piped
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        // THEN stdout is empty because Mode::Diff patch failed (Strict Contract)
        .stdout(predicate::str::is_empty());
}
