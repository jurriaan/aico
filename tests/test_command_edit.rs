mod common;
use assert_cmd::cargo::cargo_bin_cmd;
use common::init_session_with_history;
use predicates::prelude::*;
use std::env;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use tempfile::tempdir;

#[test]
fn test_edit_prompt_success() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("original prompt", "r0")]);

    // Use a shell script as faker editor that replaces content
    let editor_script = root.join("editor.sh");
    fs::write(&editor_script, "#!/bin/sh\necho 'edited prompt' > \"$1\"").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&editor_script).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&editor_script, perms).unwrap();
    }

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", editor_script.to_str().unwrap())
        .env("AICO_FORCE_EDITOR", "1")
        .args(["edit", "0", "--prompt"])
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Updated prompt for message pair 0.",
        ));

    // Verify change in history via log
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("log")
        .assert()
        .success()
        .stdout(predicate::str::contains("edited prompt"));
}

#[test]
fn test_edit_response_recomputes_derived_content_on_change() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with a file and a conversational response
    fs::write(root.join("file.py"), "print('hello')\n").unwrap();
    common::init_session_with_history(root, vec![("Change it", "Sure.")]);
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["add", "file.py"])
        .assert()
        .success();

    // AND an editor that replaces "Sure." with a valid SEARCH/REPLACE block
    // The SEARCH block must match the file content exactly, including the newline.
    let new_content =
        "File: file.py\n<<<<<<< SEARCH\nprint('hello')\n=======\nprint('world')\n>>>>>>> REPLACE";
    let editor_script = root.join("editor.sh");
    fs::write(
        &editor_script,
        format!("#!/bin/sh\necho \"{}\" > \"$1\"", new_content),
    )
    .unwrap();
    fs::set_permissions(&editor_script, fs::Permissions::from_mode(0o755)).unwrap();

    // WHEN editing the response
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", editor_script.to_str().unwrap())
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .assert()
        .success();

    // THEN the derived content (diff) should be recomputed and visible in 'last --json'
    let output = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let json: serde_json::Value = serde_json::from_slice(&output).unwrap();
    let asst = &json["assistant"];
    let diff = asst["derived"]["unified_diff"]
        .as_str()
        .expect("unified_diff should be present in derived content after edit");
    assert!(diff.contains("-print('hello')"));
    assert!(diff.contains("+print('world')"));

    // AND display items should be structured
    let display_items = asst["derived"]["display_content"]
        .as_array()
        .expect("display_content should be an array");
    assert!(display_items.iter().any(|item| {
        item["type"] == "diff"
            && item["content"]
                .as_str()
                .unwrap()
                .contains("-print('hello')")
    }));
}

#[test]
fn test_edit_with_custom_editor() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    common::init_session_with_history(root, vec![("p", "r")]);

    // Use a custom string for EDITOR with flags
    let editor_script = root.join("my_editor.sh");
    fs::write(&editor_script, "#!/bin/sh\necho \"custom editor\" > \"$2\"").unwrap();
    fs::set_permissions(&editor_script, fs::Permissions::from_mode(0o755)).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", format!("{} -f", editor_script.to_str().unwrap()))
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .stdout(predicate::str::contains("custom editor"));
}

#[test]
fn test_edit_aborts_if_no_changes() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    // A faker editor that does nothing
    let editor_script = root.join("noop_editor.sh");
    fs::write(&editor_script, "#!/bin/sh\nexit 0").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&editor_script).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&editor_script, perms).unwrap();
    }

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", editor_script.to_str().unwrap())
        .arg("edit")
        .assert()
        .success()
        .stdout(predicate::str::contains("No changes detected. Aborting."));
}

#[test]
fn test_edit_fails_on_editor_error() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", "false")
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .assert()
        .failure()
        .stderr(predicate::str::contains("Editor closed with exit code"));
}

#[test]
fn test_edit_aborts_on_editor_failure() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    // editor-script that exits with 1
    let editor_script = root.join("fail_editor.sh");
    fs::write(&editor_script, "#!/bin/sh\nexit 1").unwrap();
    fs::set_permissions(&editor_script, fs::Permissions::from_mode(0o755)).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", editor_script.to_str().unwrap())
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .assert()
        .failure()
        .stderr(predicate::str::contains(
            "Editor closed with exit code 1. Aborting.",
        ));
}

#[test]
fn test_edit_prompt() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    let editor_script = root.join("editor.sh");
    fs::write(
        &editor_script,
        "#!/bin/sh\necho 'new prompt content' > \"$1\"",
    )
    .unwrap();
    fs::set_permissions(&editor_script, fs::Permissions::from_mode(0o755)).unwrap();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", editor_script.to_str().unwrap())
        .env("AICO_FORCE_EDITOR", "1")
        .args(["edit", "--prompt"])
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--prompt"])
        .assert()
        .success()
        .stdout(predicate::str::contains("new prompt content"));
}

#[test]
fn test_edit_fails_if_editor_not_found() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", "/non/existent/editor/binary")
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .assert()
        .failure()
        .stderr(predicate::str::contains("not found. Please set $EDITOR."));
}

#[test]
fn test_edit_updates_store_and_view() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    // Use a shell script as faker editor
    let editor_script = root.join("editor.sh");
    fs::write(&editor_script, "#!/bin/sh\necho 'edited r0' > \"$1\"").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&editor_script).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&editor_script, perms).unwrap();
    }

    // WHEN editing the assistant response (index 0, which corresponds to pair 0)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", editor_script.to_str().unwrap())
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .assert()
        .success();

    // THEN the view is updated to point to a new record ID
    let view = common::load_view(root);
    // Original indices were [0, 1]. New should be [0, 2]
    assert_eq!(view.message_indices.len(), 2);
    assert_eq!(view.message_indices[0], 0);
    assert!(view.message_indices[1] > 1);

    // AND the store contains both the original and the new edit
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(history_path).unwrap();
    assert!(content.contains("r0"));
    assert!(content.contains("edited r0"));
    assert!(content.contains("\"edit_of\":1"));
}

#[test]
fn test_edit_response_and_invalidate_derived_content() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    // Manually inject derived content into the history record by parsing and re-serializing
    let history_path = root.join(".aico/history/0.jsonl");
    let content = fs::read_to_string(&history_path).unwrap();
    let lines: Vec<&str> = content.lines().collect();
    let mut rec: aico::models::HistoryRecord = serde_json::from_str(lines[1]).unwrap();

    rec.derived = Some(aico::models::DerivedContent {
        unified_diff: Some("some diff".to_string()),
        display_content: None,
    });

    let updated_line = serde_json::to_string(&rec).unwrap();
    fs::write(&history_path, format!("{}\n{}\n", lines[0], updated_line)).unwrap();

    // Verify derived content is there
    let output_before = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    assert!(
        String::from_utf8(output_before)
            .unwrap()
            .contains("some diff")
    );

    let editor_script = root.join("editor.sh");
    fs::write(
        &editor_script,
        "#!/bin/sh\necho 'conversational edit' > \"$1\"",
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&editor_script).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&editor_script, perms).unwrap();
    }

    // WHEN editing (provide empty stdin to prevent hang in non-TTY test environment)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", editor_script.to_str().unwrap())
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .write_stdin("")
        .assert()
        .success();

    // THEN the new record in JSON output should NOT have derived content
    // because it was a simple text edit
    let output_after = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let json_after: serde_json::Value = serde_json::from_slice(&output_after).unwrap();
    assert!(json_after["assistant"]["derived"].is_null());
}

#[test]
fn test_edit_scripted_mode() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "original response")]);

    // WHEN running aico edit in a non-tty environment (stdin is redirected)
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("edit")
        .write_stdin("new response from stdin")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Updated response for message pair 0.",
        ));

    // THEN the response content is updated
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .stdout(predicate::str::contains("new response from stdin"));
}

#[test]
fn test_edit_scripted_mode_empty_stdin() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "original response")]);

    // WHEN running aico edit with empty piped input
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("edit")
        .write_stdin("")
        .assert()
        .success()
        .stdout(predicate::str::contains("No changes detected. Aborting."));

    // THEN the response remains unchanged
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .stdout(predicate::str::contains("original response"));
}

#[test]
fn test_edit_fails_on_bad_index() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0")]);

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["edit", "99"])
        .assert()
        .failure()
        .stderr(predicate::str::contains("Index out of bounds"));
}

#[test]
fn test_edit_negative_index() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();

    init_session_with_history(root, vec![("p0", "r0"), ("p1", "r1")]);

    // -1 highlights the last pair
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["edit", "-1"])
        .write_stdin("updated last")
        .assert()
        .success()
        .stdout(predicate::str::contains(
            "Updated response for message pair 1.",
        ));

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .stdout(predicate::str::contains("updated last"));
}

#[test]
fn test_edit_preserves_original_timestamp() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session with one pair
    common::init_session_with_history(root, vec![("p0", "r0")]);

    // AND we capture the original timestamp
    let output_before = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let json_before: serde_json::Value = serde_json::from_slice(&output_before).unwrap();
    let original_ts = json_before["assistant"]["timestamp"].as_str().unwrap();

    // WHEN editing the response via piped input
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("edit")
        .write_stdin("edited response")
        .assert()
        .success();

    // THEN the timestamp remains unchanged
    let output_after = cargo_bin_cmd!("aico")
        .current_dir(root)
        .args(["last", "--json"])
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let json_after: serde_json::Value = serde_json::from_slice(&output_after).unwrap();
    let new_ts = json_after["assistant"]["timestamp"].as_str().unwrap();

    assert_eq!(original_ts, new_ts, "Timestamp was changed during edit!");
}

#[test]
fn test_edit_handles_editor_path_with_spaces() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    common::init_session_with_history(root, vec![("p", "original")]);

    // Create a directory with spaces and a script inside
    let editor_dir = root.join("my editor");
    fs::create_dir_all(&editor_dir).unwrap();
    let editor_script = editor_dir.join("edit.sh");

    // Script that writes to the last argument (the file path)
    fs::write(
        &editor_script,
        "#!/bin/sh\nfor last; do :; done\necho \"space editor\" > \"$last\"",
    )
    .unwrap();
    fs::set_permissions(&editor_script, fs::Permissions::from_mode(0o755)).unwrap();

    // Wrap the path in quotes to simulate a robust $EDITOR configuration
    let editor_val = format!("\"{}\" -f", editor_script.to_str().unwrap());

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", editor_val)
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .stdout(predicate::str::contains("space editor"));
}

#[test]
fn test_edit_handles_editor_with_flags_string() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    common::init_session_with_history(root, vec![("p", "original")]);

    // Set EDITOR to something that mimics a command with flags
    // Under Unix, we can use 'sed' to replace the content
    cargo_bin_cmd!("aico")
        .current_dir(root)
        .env("EDITOR", "sed -i s/original/modified/g")
        .env("AICO_FORCE_EDITOR", "1")
        .arg("edit")
        .assert()
        .success();

    cargo_bin_cmd!("aico")
        .current_dir(root)
        .arg("last")
        .assert()
        .success()
        .stdout(predicate::str::contains("modified"));
}
