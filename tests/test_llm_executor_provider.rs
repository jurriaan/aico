use aico::llm::executor::extract_reasoning_header;

#[test]
fn test_extract_reasoning_header_markdown() {
    // Single Markdown header
    assert_eq!(
        extract_reasoning_header("### Planning\nNext steps"),
        Some("Planning".to_string())
    );
}

#[test]
fn test_extract_reasoning_header_bold() {
    // Single bold
    assert_eq!(
        extract_reasoning_header("**Analysis** in progress"),
        Some("Analysis".to_string())
    );
}

#[test]
fn test_extract_reasoning_header_last_match() {
    // Multiple headers, last wins
    assert_eq!(
        extract_reasoning_header("## First\n### Second\n**Final**"),
        Some("Final".to_string())
    );
}

#[test]
fn test_extract_reasoning_header_no_match() {
    // No match
    assert_eq!(extract_reasoning_header("Plain text without headers"), None);
}

#[test]
fn test_extract_reasoning_header_malformed() {
    // Malformed/incomplete
    assert_eq!(extract_reasoning_header("**Unclosed"), None);
    assert_eq!(extract_reasoning_header("#### "), None);
}
