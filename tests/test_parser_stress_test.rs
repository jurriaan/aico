use aico::diffing::parser::StreamParser;
use aico::models::StreamYieldItem;
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug)]
struct TestCase {
    name: &'static str,
    files: Vec<(&'static str, &'static str)>,
    stream_input: &'static str,
}

fn get_cases() -> Vec<TestCase> {
    vec![
        TestCase {
            name: "Standard Replacement",
            files: vec![("main.rs", "fn main() {\n    println!(\"Old\");\n}\n")],
            stream_input: "File: main.rs\n<<<<<<< SEARCH\n    println!(\"Old\");\n=======\n    println!(\"New\");\n>>>>>>> REPLACE\n",
        },
        TestCase {
            name: "File Creation",
            files: vec![],
            stream_input: "File: new_script.py\n<<<<<<< SEARCH\n=======\nprint('Hello World')\n>>>>>>> REPLACE\n",
        },
        TestCase {
            name: "Python Indentation Patch",
            files: vec![(
                "utils.py",
                "def check(x):\n    if x:\n        return True\n    return False\n",
            )],
            stream_input: "File: utils.py\n<<<<<<< SEARCH\n    if x:\n        return True\n=======\n    if x:\n        # Logging added\n        print(x)\n        return True\n>>>>>>> REPLACE\n",
        },
        TestCase {
            name: "Adjacent Markers (The Tricky Case)",
            files: vec![("config.txt", "A=1\nB=1\n")],
            stream_input: "File: config.txt\n<<<<<<< SEARCH\nA=1\n=======\nA=2\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nB=1\n=======\nB=2\n>>>>>>> REPLACE\n",
        },
        TestCase {
            name: "With Conversational Noise",
            files: vec![("readme.md", "# Title\nOld Body")],
            stream_input: "I will update the readme now.\n\nFile: readme.md\n<<<<<<< SEARCH\nOld Body\n=======\nNew Body\n>>>>>>> REPLACE\n\nThere, all done.",
        },
        TestCase {
            name: "Unicode Characters (Safety Check)",
            files: vec![("emoji.txt", "Old: 😐")],
            stream_input: "File: emoji.txt\n<<<<<<< SEARCH\nOld: 😐\n=======\nNew: 😎\n>>>>>>> REPLACE\n",
        },
        TestCase {
            name: "Windows Line Endings (CRLF)",
            files: vec![("windows.txt", "line1\r\nline2\r\n")],
            stream_input: "File: windows.txt\r\n<<<<<<< SEARCH\r\nline1\r\n=======\r\nline1_modified\r\n>>>>>>> REPLACE\r\n",
        },
    ]
}

fn run_parser_with_chunks(files: &[(&str, &str)], chunks: &[&str]) -> Vec<StreamYieldItem> {
    let mut context = HashMap::new();
    for (name, content) in files {
        context.insert(name.to_string(), content.to_string());
    }

    let mut parser = StreamParser::new(&context);
    let mut all_resolved_items = Vec::new();

    // 1. Processing Loop (Mimics executor.rs)
    for chunk in chunks {
        // parse_and_resolve performs: feed() -> collect() -> process_yields()
        let resolved = parser.parse_and_resolve(chunk, Path::new("."));
        all_resolved_items.extend(resolved);
    }

    // 2. Finalization (Mimics final_resolve)
    // We manually finish and process yields to capture the StreamYieldItems
    // (final_resolve returns DisplayItems which loses type info)
    let (_, final_raw, _) = parser.finish("");
    let final_resolved = parser.process_yields(final_raw, Path::new("."));
    all_resolved_items.extend(final_resolved);

    normalize_items(all_resolved_items)
}

fn normalize_items(items: Vec<StreamYieldItem>) -> Vec<StreamYieldItem> {
    let mut normalized = Vec::new();
    let mut text_buf = String::new();

    let flush = |buf: &mut String, out: &mut Vec<StreamYieldItem>| {
        if !buf.is_empty() {
            out.push(StreamYieldItem::Text(std::mem::take(buf)));
        }
    };

    for item in items {
        match item {
            StreamYieldItem::Text(t) | StreamYieldItem::IncompleteBlock(t) => {
                text_buf.push_str(&t);
            }
            other => {
                flush(&mut text_buf, &mut normalized);
                normalized.push(other);
            }
        }
    }
    flush(&mut text_buf, &mut normalized);
    normalized
}

#[test]
fn test_parser_stress_consistency() {
    for case in get_cases() {
        println!("Testing Case: {}", case.name);

        // --- 1. Reference Run (Single Chunk) ---
        let reference_items = run_parser_with_chunks(&case.files, &[case.stream_input]);

        // VALIDITY CHECK
        let success = reference_items
            .iter()
            .any(|i| matches!(i, StreamYieldItem::DiffBlock(_)));
        let warnings: Vec<_> = reference_items.iter().filter(|i| i.is_warning()).collect();

        if !success || !warnings.is_empty() {
            panic!(
                "\n🚨 TEST FAILURE: Scenario '{}' Reference Run Failed!\n\
                    Reason: The parser failed to produce a valid patch even when given the full string.\n\
                    \n--- INPUT ---\n{:?}\n\
                    \n--- ACTUAL FOUND ---\nDiffBlocks: {}\nWarnings: {}\n\
                    \n--- FULL OUTPUT ITEMS ---\n{:#?}\n",
                case.name,
                case.stream_input,
                reference_items
                    .iter()
                    .filter(|i| matches!(i, StreamYieldItem::DiffBlock(_)))
                    .count(),
                warnings.len(),
                reference_items
            );
        }

        // --- 2. Drip Feed Run (Char-by-Char) ---
        let chars: Vec<String> = case.stream_input.chars().map(|c| c.to_string()).collect();
        let char_chunks: Vec<&str> = chars.iter().map(|s| s.as_str()).collect();
        let drip_items = run_parser_with_chunks(&case.files, &char_chunks);

        if reference_items != drip_items {
            panic!(
                "\n🚨 TEST FAILURE: Scenario '{}' Consistency Check Failed (Char-by-Char).\n\
                    The output changed when fed character by character.\n\
                    \n--- REFERENCE OUTPUT ---\n{:#?}\n\
                    \n--- DRIP FEED OUTPUT ---\n{:#?}\n",
                case.name, reference_items, drip_items
            );
        }

        // --- 3. Brute Force Split Run ---
        for (char_idx, (byte_idx, _)) in case.stream_input.char_indices().enumerate() {
            if byte_idx == 0 {
                continue;
            }

            let (part1, part2) = case.stream_input.split_at(byte_idx);
            let split_items = run_parser_with_chunks(&case.files, &[part1, part2]);

            if reference_items != split_items {
                panic!(
                    "\n🚨 TEST FAILURE: Scenario '{}' Consistency Check Failed.\n\
                        The output changed when split at char index {} (byte {}).\n\
                        \n--- SPLIT POINT ---\nPart 1 Tail: {:?}\nPart 2 Head: {:?}\n\
                        \n--- REFERENCE OUTPUT ---\n{:#?}\n\
                        \n--- SPLIT OUTPUT ---\n{:#?}\n",
                    case.name,
                    char_idx,
                    byte_idx,
                    &part1[part1.len().saturating_sub(10)..],
                    &part2[..part2.len().min(10)],
                    reference_items,
                    split_items
                );
            }
        }
    }
}
