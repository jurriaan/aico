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

    // Rust's replace replaces all occurrences, we only want the first one.
    if let Some(idx) = original.find(search) {
        let mut res = String::with_capacity(original.len() - search.len() + replace.len());
        res.push_str(&original[..idx]);
        res.push_str(replace);
        res.push_str(&original[idx + search.len()..]);
        Some(res)
    } else {
        None
    }
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
    let match_start_index =
        (0..=original_lines.len().saturating_sub(search_lines.len())).find(|&i| {
            let end_idx = i + search_lines.len();
            if end_idx > original_lines.len() {
                return false;
            }
            let slice = &original_lines[i..end_idx];
            slice
                .iter()
                .zip(&stripped_search)
                .all(|(orig, stripped)| orig.trim_end_matches(['\n', '\r']).trim() == *stripped)
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
    let meaningful_lines: Vec<&str> = lines
        .iter()
        .filter(|l| !l.trim().is_empty())
        .cloned()
        .collect();

    if meaningful_lines.is_empty() {
        return String::new();
    }

    // Start with the first line's indentation as the candidate
    let first = meaningful_lines[0];
    let indent_len = first.len() - first.trim_start().len();
    let mut common_indent = &first[..indent_len];

    for line in &meaningful_lines[1..] {
        let mut common_len = 0;
        for ((i, c1), c2) in common_indent.char_indices().zip(line.chars()) {
            if c1 == c2 {
                common_len = i + c1.len_utf8();
            } else {
                break;
            }
        }
        common_indent = &common_indent[..common_len];

        if common_indent.is_empty() {
            break;
        }
    }

    common_indent.to_string()
}
