import difflib
import re


def _generate_new_content(
    original_content: str, search_block: str, replace_block: str
) -> str | None:
    """
    Generates the new file content based on search/replace blocks.
    Returns None if the search block is not found in the original content.
    """
    # Handle file creation
    if not search_block and not original_content:
        return replace_block

    # Handle file deletion
    if not replace_block and search_block == original_content:
        return ""

    # Ensure the search block is actually in the original content
    if search_block not in original_content:
        return None

    # Use replace with a count of 1 to avoid unintended multiple replacements
    return original_content.replace(search_block, replace_block, 1)


def generate_diff_from_response(
    original_file_contents: dict[str, str], llm_response: str
) -> str:
    """
    Parses SEARCH/REPLACE blocks from the LLM response and generates a unified diff.
    """
    # Defensive parsing: find the first `File:` block and ignore any text before it.
    match = re.search(r"^File: ", llm_response, re.MULTILINE)
    if not match:
        return (
            "--- a/LLM_RESPONSE_ERROR\n"
            "+++ b/LLM_RESPONSE_ERROR\n"
            "@@ -1,2 +1,3 @@\n"
            "-Could not find any 'File: ...' blocks in the AI's response.\n"
            "+This may be due to a malformed response or conversational filler.\n"
            f"+Full Response:\n{llm_response}"
        )

    clean_response = llm_response[match.start() :]

    # Split the response into blocks, each starting with "File: <path>"
    # (?=...) is a positive lookahead to keep the "File: " delimiter in the split.
    file_blocks = re.split(r"^(?=File: )", clean_response, flags=re.MULTILINE)

    unified_diff_parts = []

    for block in file_blocks:
        block = block.strip()
        if not block:
            continue

        # Extract file path from the "File: <path>" header
        header_match = re.match(r"File: (.*?)\n", block)
        if not header_match:
            unified_diff_parts.append(
                f"--- a/BLOCK_PARSE_ERROR\n"
                f"+++ b/BLOCK_PARSE_ERROR\n"
                f"@@ -1 +1 @@\n"
                f"-Could not parse file path from malformed block:\n"
                f"+{block}\n"
            )
            continue

        file_path = header_match.group(1).strip()

        # Extract SEARCH/REPLACE content
        search_replace_match = re.search(
            r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
            block,
            re.DOTALL,
        )

        if not search_replace_match:
            unified_diff_parts.append(
                f"--- a/{file_path}\n"
                f"+++ b/{file_path}\n"
                f"@@ -1 +2 @@\n"
                f"-Error processing block for '{file_path}': Could not parse SEARCH/REPLACE markers.\n"
                f"-Block Content:\n+{block}"
            )
            continue

        # Use rstrip to handle trailing newlines consistently
        search_content = search_replace_match.group(1).rstrip("\n")
        replace_content = search_replace_match.group(2).rstrip("\n")

        from_file = f"a/{file_path}"
        to_file = f"b/{file_path}"

        original_content = original_file_contents.get(file_path, "")

        new_content_full = _generate_new_content(
            original_content, search_content, replace_content
        )

        if new_content_full is None:
            # Handle case where search block wasn't found in the original file
            unified_diff_parts.append(
                f"--- a/{file_path}\n"
                f"+++ b/{file_path}\n"
                f"@@ -1 +3 @@\n"
                f"-Error: The SEARCH block from the AI did not match the content of '{file_path}'.\n"
                f"-The file content may have changed or the AI made a mistake.\n"
                f"-Provided SEARCH block:\n+{search_content}"
            )
            continue

        original_content_lines = original_content.splitlines(keepends=True)
        new_content_lines = new_content_full.splitlines(keepends=True)

        if not original_content and not search_content:  # New file
            from_file = "/dev/null"
        elif not new_content_full and original_content:  # Deleted file
            to_file = "/dev/null"

        diff_lines = list(
            difflib.unified_diff(
                original_content_lines,
                new_content_lines,
                fromfile=from_file,
                tofile=to_file,
            )
        )
        unified_diff_parts.extend(diff_lines)

    return "".join(unified_diff_parts)
