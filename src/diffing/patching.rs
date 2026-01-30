pub fn create_patched_content(
    original_content: &str,
    search_block: &str,
    replace_block: &str,
) -> Option<String> {
    // Stage 1: Exact match
    if let Some(patched) = try_exact_string_patch(original_content, search_block, replace_block) {
        return Some(patched);
    }

    // Stage 2: Whitespace-flexible match
    try_whitespace_flexible_patch(original_content, search_block, replace_block)
}

fn try_exact_string_patch(original: &str, search: &str, replace: &str) -> Option<String> {
    // Handle file creation
    if search.is_empty() && original.is_empty() {
        return Some(replace.to_string());
    }

    // Handle file deletion
    if replace.is_empty() && search == original {
        return Some(String::new());
    }

    if search.trim().is_empty() {
        return None;
    }

    original
        .find(search)
        .map(|_| original.replacen(search, replace, 1))
}

fn try_whitespace_flexible_patch(original: &str, search: &str, replace: &str) -> Option<String> {
    // Port of python lines logic: split_inclusive keeps newlines.
    // We normalize to \n conceptually by using .trim_end_matches(['\n', '\r'])
    let original_lines: Vec<&str> = original.split_inclusive('\n').collect();
    let search_lines: Vec<&str> = search.split_inclusive('\n').collect();
    let replace_lines: Vec<&str> = replace.split_inclusive('\n').collect();

    if search_lines.is_empty() || search_lines.len() > original_lines.len() {
        return None;
    }

    let stripped_search: Vec<&str> = search_lines
        .iter()
        .map(|s| s.trim_end_matches(['\n', '\r']).trim())
        .collect();
    if stripped_search.iter().all(|s| s.is_empty()) {
        return None;
    }

    // Find match index
    let match_start_index = original_lines
        .windows(search_lines.len())
        .position(|window| {
            window
                .iter()
                // Inline the normalization logic here to avoid lifetime errors
                .map(|s| s.trim_end_matches(['\n', '\r']).trim())
                .eq(stripped_search.iter().cloned())
        });

    let start_idx = match_start_index?;

    // Calculate indentation
    let matched_chunk = &original_lines[start_idx..start_idx + search_lines.len()];
    let original_indent = get_consistent_indentation(matched_chunk);
    let replace_indent = get_consistent_indentation(&replace_lines);

    let mut new_lines: Vec<String> = Vec::new();

    // Pre-match
    new_lines.extend(original_lines[..start_idx].iter().map(|s| s.to_string()));

    // Replaced block
    for line in replace_lines {
        // Carry over the line content including its original trailing whitespace/newline
        // because original_lines and replace_lines were split_inclusive.
        if line.trim().is_empty() {
            new_lines.push(line.to_string());
            continue;
        }

        let relative = if !replace_indent.is_empty() && line.starts_with(&replace_indent) {
            &line[replace_indent.len()..]
        } else {
            line
        };
        new_lines.push(format!("{}{}", original_indent, relative));
    }

    // Post-match
    new_lines.extend(
        original_lines[start_idx + search_lines.len()..]
            .iter()
            .map(|s| s.to_string()),
    );

    Some(new_lines.concat())
}

fn get_consistent_indentation(lines: &[&str]) -> String {
    lines
        .iter()
        .filter(|line| !line.trim().is_empty()) // Ignore blank lines
        .cloned()
        .reduce(|acc, line| {
            // Find common prefix between accumulator and current line
            acc.char_indices()
                .zip(line.chars())
                .take_while(|((_, c1), c2)| c1 == c2)
                .map(|((i, c), _)| &acc[..i + c.len_utf8()])
                .last()
                .unwrap_or("") // Fallback to empty string if no common prefix
        })
        .map(|s| {
            // Ensure we only captured whitespace
            let ws_len = s.chars().take_while(|c| c.is_whitespace()).count();
            // Convert byte-slice back to char-aware string slice logic if needed,
            // but simply creating a string from the whitespace prefix is safer.
            s.chars().take(ws_len).collect()
        })
        .unwrap_or_default()
}
