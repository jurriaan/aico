use aico::llm::executor::extract_reasoning_header;

#[test]
fn test_reasoning_header_extraction_variants() {
    // GIVEN various reasoning buffers
    let cases = vec![
        ("### Reasoning\nChecking logic...", Some("Reasoning")),
        ("**Analysis**\nThe code has a bug...", Some("Analysis")),
        (
            "## Step 1\n### Step 2\n**Final Thought**",
            Some("Final Thought"),
        ),
        ("Just some text without headers", None),
        ("####   Spaced Header   ", Some("Spaced Header")),
        ("**  Spaced Bold  **", Some("Spaced Bold")),
    ];

    for (input, expected) in cases {
        // WHEN extracting the header
        let result = extract_reasoning_header(input);

        // THEN it matches the expected last markdown/bold header
        assert_eq!(result.as_deref(), expected, "Failed on input: {}", input);
    }
}
