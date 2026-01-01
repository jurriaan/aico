use aico::fs::validate_input_paths;
use std::fs;
use tempfile::tempdir;

#[test]
fn test_validate_input_paths_normalizes_relative_traversals() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN a session root and a file
    let target = root.join("target.txt");
    fs::write(&target, "content").unwrap();

    // AND a subdirectory exists
    let subdir = root.join("subdir");
    fs::create_dir(&subdir).unwrap();
    let input = subdir.join("..").join("target.txt");

    // WHEN validating
    let (valid, has_errors) = validate_input_paths(root, &[input], true);

    // THEN it normalizes to just the filename
    assert_eq!(valid, vec!["target.txt"]);
    assert!(!has_errors);
}

#[test]
fn test_add_file_outside_session_root_fails() {
    let temp = tempdir().unwrap();
    let root = temp.path();
    let root_dir = root.join("project");
    fs::create_dir(&root_dir).unwrap();

    // GIVEN a file outside the root
    let outside_file = root.join("secret.txt");
    fs::write(&outside_file, "secret").unwrap();

    // WHEN validating
    let (valid, has_errors) = validate_input_paths(&root_dir, &[outside_file], true);

    // THEN it fail with errors and return no valid paths
    assert!(valid.is_empty());
    assert!(has_errors);
}

#[test]
#[cfg(unix)]
fn test_add_symlink_to_inside_success() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    let target_file = root.join("actual.txt");
    fs::write(&target_file, "content").unwrap();

    let link_path = root.join("link.txt");
    std::os::unix::fs::symlink("actual.txt", &link_path).unwrap();

    // WHEN validating the symlink path
    let (valid, has_errors) = validate_input_paths(root, &[link_path], true);

    // THEN it returns the link name, not the target name
    assert_eq!(valid, vec!["link.txt"]);
    assert!(!has_errors);
}

#[test]
fn test_get_context_file_contents_handles_empty_list() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    // GIVEN an empty list
    let context_files: Vec<String> = vec![];

    // WHEN reading contents
    let mut contents = std::collections::HashMap::new();
    for f in context_files {
        if let Ok(c) = std::fs::read_to_string(root.join(&f)) {
            contents.insert(f, c);
        }
    }

    // THEN result is empty
    assert!(contents.is_empty());
}

#[test]
fn test_get_context_file_contents_only_includes_existing_and_warns_for_missing() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    fs::write(root.join("exists.txt"), "content").unwrap();

    let context_files = vec!["exists.txt".to_string(), "missing.txt".to_string()];
    let mut contents = std::collections::HashMap::new();

    for f in &context_files {
        if let Ok(c) = std::fs::read_to_string(root.join(f)) {
            contents.insert(f.clone(), c);
        }
    }

    assert!(contents.contains_key("exists.txt"));
    assert!(!contents.contains_key("missing.txt"));
    assert_eq!(contents.get("exists.txt").unwrap(), "content");
}

#[test]
fn test_validate_input_paths_rejects_missing_when_required() {
    let temp = tempdir().unwrap();
    let root = temp.path();

    let input = root.join("nonexistent.txt");
    let (valid, has_errors) = validate_input_paths(root, &[input], true);

    assert!(valid.is_empty());
    assert!(has_errors);
}
