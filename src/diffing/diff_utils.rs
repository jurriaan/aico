use similar::TextDiff;
use std::borrow::Cow;

pub fn generate_diff(
    filename: &str,
    old_content: Option<&str>,
    new_content: Option<&str>,
) -> String {
    let from_header = if old_content.is_none() {
        "/dev/null".to_string()
    } else {
        format!("a/{}", filename)
    };

    let to_header = if new_content.is_none()
        || (new_content == Some("") && !old_content.unwrap_or("").is_empty())
    {
        "/dev/null".to_string()
    } else {
        format!("b/{}", filename)
    };

    let old_text = old_content.unwrap_or("");
    let new_text = new_content.unwrap_or("");

    let diff = TextDiff::from_lines(old_text, new_text)
        .unified_diff()
        .header(&quote_filename(&from_header), &quote_filename(&to_header))
        .missing_newline_hint(true)
        .to_string();

    // The 'similar' crate omits headers if there are no hunks.
    // We force headers for creations/deletions of empty files.
    if diff.is_empty() && old_content.is_none() != new_content.is_none() {
        return format!(
            "--- {}\n+++ {}\n",
            quote_filename(&from_header),
            quote_filename(&to_header)
        );
    }

    diff
}

fn quote_filename(filename: &str) -> Cow<'_, str> {
    if filename.contains(' ') {
        format!("\"{}\"", filename).into()
    } else {
        filename.into()
    }
}
