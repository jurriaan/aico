use assert_cmd::cargo::cargo_bin_cmd;

#[test]
fn test_no_command_shows_help() {
    let output = cargo_bin_cmd!("aico")
        .assert()
        // Clap exits with 2 for missing required subcommands
        .get_output()
        .stderr
        .clone();

    let stderr = String::from_utf8(output).unwrap();
    assert!(stderr.contains("Usage: aico <COMMAND>"));
    assert!(stderr.contains("Commands:"));
    assert!(stderr.contains("status"));
    assert!(stderr.contains("log"));
}

#[test]
fn test_gen_alias_is_recognized() {
    // GIVEN the app
    // WHEN running with the 'generate-patch' alias and no args
    let assert = cargo_bin_cmd!("aico").arg("generate-patch").assert();

    // THEN it should be recognized as a command (it will fail with "Prompt is required"
    // but the exit code will be 1 from our validator, not 2 from clap's unknown command)
    let assert = assert.failure().code(1);
    let stderr = String::from_utf8_lossy(&assert.get_output().stderr);
    assert!(stderr.contains("Error: Invalid input: Prompt is required."));
}
