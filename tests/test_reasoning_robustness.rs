use aico::llm::executor::extract_reasoning_header;

#[test]
fn test_reasoning_extraction_consolidated() {
    let cases = vec![
        // Basic Markdown - Requires newline to be stable during streaming
        ("### Planning\n", Some("Planning")),
        // Bold headers - Stable because they require closing **
        ("**Analysis**", Some("Analysis")),
        // Last match wins
        (
            "## Step 1\n### Step 2\n**Final Thought**",
            Some("Final Thought"),
        ),
        // PREVENT FLICKER: Partial Markdown header without newline should return None
        ("### Evalu", None),
        // SPACING
        ("####   Spaced Header   \n", Some("Spaced Header")),
        ("**  Spaced Bold  **", Some("Spaced Bold")),
        // MALFORMED
        ("Just text", None),
        ("#### ", None),
        ("**Unclosed", None),
    ];

    for (input, expected) in cases {
        let result = extract_reasoning_header(input);
        assert_eq!(result.as_deref(), expected, "Failed on input: {:?}", input);
    }
}

#[test]
fn test_extract_reasoning_header_incremental_bold() {
    let chunks = vec![
        "**Ref",
        "ining",
        " Markdown",
        " Header",
        " Processing",
        "**\n\nI",
    ];

    let mut buffer = String::new();

    // Step 1: "**Ref" -> Should be None (waiting for closing **)
    buffer.push_str(chunks[0]);
    assert_eq!(
        extract_reasoning_header(&buffer),
        None,
        "Partial bold header matched prematurely: '{}'",
        buffer
    );

    // Step 2-5: Accumulating -> Should still be None
    for i in 1..5 {
        buffer.push_str(chunks[i]);
        assert_eq!(
            extract_reasoning_header(&buffer),
            None,
            "Partial bold header matched prematurely at chunk {}: '{}'",
            i,
            buffer
        );
    }

    // Step 6: Closing "**" -> Should Match Full String
    buffer.push_str(chunks[5]);
    assert_eq!(
        extract_reasoning_header(&buffer),
        Some("Refining Markdown Header Processing".to_string()),
        "Failed to match complete bold header"
    );
}
