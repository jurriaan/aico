import difflib
import re
from pathlib import Path


def _try_exact_string_patch(
    original_content: str, search_block: str, replace_block: str
) -> str | None:
    # Handle file creation
    if not search_block and not original_content:
        return replace_block

    # Handle file deletion
    if not replace_block and search_block == original_content:
        return ""

    if search_block not in original_content:
        return None

    # Use replace with a count of 1 to avoid unintended multiple replacements
    return original_content.replace(search_block, replace_block, 1)


def _get_consistent_indentation(lines: list[str]) -> str | None:
    indentation_set = {
        line[: len(line) - len(line.lstrip())] for line in lines if line.strip()
    }

    if len(indentation_set) > 1:
        return None

    return indentation_set.pop() if indentation_set else ""


def _try_whitespace_flexible_patch(
    original_content: str, search_block: str, replace_block: str
) -> str | None:
    original_lines = original_content.splitlines(keepends=True)
    search_lines = search_block.splitlines(keepends=True)
    replace_lines = replace_block.splitlines(keepends=True)

    if not search_lines:
        return None

    stripped_search_lines = [line.lstrip() for line in search_lines]

    matching_block_start_indices = []
    for i in range(len(original_lines) - len(search_lines) + 1):
        original_lines_chunk = original_lines[i : i + len(search_lines)]
        stripped_original_lines_chunk = [
            line.lstrip() for line in original_lines_chunk
        ]

        if stripped_original_lines_chunk == stripped_search_lines:
            matching_block_start_indices.append(i)

    if len(matching_block_start_indices) != 1:
        return None

    match_start_index = matching_block_start_indices[0]
    matched_original_lines_chunk = original_lines[
        match_start_index : match_start_index + len(search_lines)
    ]

    base_indentation = _get_consistent_indentation(matched_original_lines_chunk)
    if base_indentation is None:
        return None

    indented_replace_lines = [
        base_indentation + line if line.strip() else line for line in replace_lines
    ]

    new_content_lines = (
        original_lines[:match_start_index]
        + indented_replace_lines
        + original_lines[match_start_index + len(search_lines) :]
    )

    return "".join(new_content_lines)


def _create_patched_content(
    original_content: str, search_block: str, replace_block: str
) -> str | None:
    # Stage 1: Exact match
    patched_content = _try_exact_string_patch(
        original_content, search_block, replace_block
    )
    if patched_content is not None:
        return patched_content

    # Stage 2: Whitespace-insensitive match
    patched_content = _try_whitespace_flexible_patch(
        original_content, search_block, replace_block
    )
    if patched_content is not None:
        return patched_content

    return None


def _find_best_matching_filename(
    llm_path: str, available_paths: list[str]
) -> str | None:
    # 1. Exact Match
    if llm_path in available_paths:
        return llm_path

    # 2. Basename Match
    llm_basename = Path(llm_path).name
    for path in available_paths:
        if Path(path).name == llm_basename:
            return path

    # 3. Fuzzy match
    close_matches = difflib.get_close_matches(llm_path, available_paths, n=1, cutoff=0.8)
    if close_matches:
        return close_matches[0]

    return None


def _parse_llm_edit_block(block_text: str) -> dict[str, str] | None:
    header_match = re.match(r"File: (.*?)\n", block_text)
    if not header_match:
        return None

    llm_file_path = header_match.group(1).strip()

    search_replace_match = re.search(
        r"<<<<<<< SEARCH\n(.*?)\n?=======\n(.*?)\n>>>>>>> REPLACE",
        block_text,
        re.DOTALL,
    )

    if not search_replace_match:
        return None

    search_content = search_replace_match.group(1).rstrip("\n")
    replace_content = search_replace_match.group(2).rstrip("\n")

    return {
        "llm_file_path": llm_file_path,
        "search_content": search_content,
        "replace_content": replace_content,
    }


def _generate_diff_for_single_block(
    parsed_block: dict[str, str], original_file_contents: dict[str, str]
) -> str:
    llm_file_path = parsed_block["llm_file_path"]
    search_content = parsed_block["search_content"]
    replace_content = parsed_block["replace_content"]

    file_path = _find_best_matching_filename(
        llm_file_path, list(original_file_contents.keys())
    )

    if file_path:
        original_content = original_file_contents[file_path]
    elif search_content == "":
        # This is a new file creation
        file_path = llm_file_path
        original_content = ""
    else:
        # The file was not found, and it's not a new file instruction.
        return (
            f"--- a/{llm_file_path} (not found)\n"
            f"+++ b/{llm_file_path} (not found)\n"
            f"@@ -1 +2 @@\n"
            f"-Error: The file path '{llm_file_path}' from the AI does not match any file in the context.\n"
            f"+Skipping this block."
        )

    new_content_full = _create_patched_content(
        original_content, search_content, replace_content
    )

    if new_content_full is None:
        error_message_lines = (
            [
                f"Error: The SEARCH block from the AI could not be found in '{file_path}'.\n",
                "This can happen if the file has changed, or if the AI made a mistake.\n\n",
                "The AI provided the following SEARCH block:\n",
                "--- SEARCH BLOCK ---\n",
            ]
            + search_content.splitlines(keepends=True)
            + ["--- END SEARCH BLOCK ---\n"]
        )
        return "".join(
            difflib.unified_diff(
                [],
                error_message_lines,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path} (patch failed)",
            )
        )

    from_file = f"a/{file_path}"
    to_file = f"b/{file_path}"
    original_content_lines = original_content.splitlines(keepends=True)
    new_content_lines = new_content_full.splitlines(keepends=True)

    if not original_content and not search_content:
        from_file = "/dev/null"
    elif not new_content_full and original_content:
        to_file = "/dev/null"

    diff_lines = list(
        difflib.unified_diff(
            original_content_lines,
            new_content_lines,
            fromfile=from_file,
            tofile=to_file,
        )
    )
    return "".join(diff_lines)


def generate_diff_from_response(
    original_file_contents: dict[str, str], llm_response: str
) -> str:
    unified_diff_parts = []
    file_block_start_pattern = re.compile(r"^File: ", re.MULTILINE)

    matches = list(file_block_start_pattern.finditer(llm_response))

    if not matches:
        return (
            "--- a/LLM_RESPONSE_ERROR\n"
            "+++ b/LLM_RESPONSE_ERROR\n"
            "@@ -1,2 +1,3 @@\n"
            "-Could not find any 'File: ...' blocks in the AI's response.\n"
            "+This may be due to a malformed response or conversational filler.\n"
            f"+Full Response:\n{llm_response}"
        )

    for i, match in enumerate(matches):
        start_pos = match.start()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(llm_response)
        block = llm_response[start_pos:end_pos].strip()

        if not block:
            continue

        parsed_block = _parse_llm_edit_block(block)

        if not parsed_block:
            unified_diff_parts.append(
                f"--- a/MALFORMED_BLOCK\n"
                f"+++ b/MALFORMED_BLOCK\n"
                f"@@ -1 +2 @@\n"
                f"-Error: Could not parse malformed edit block.\n"
                f"+{block}\n"
            )
            continue

        diff_for_block = _generate_diff_for_single_block(
            parsed_block, original_file_contents
        )
        unified_diff_parts.append(diff_for_block)

    return "".join(unified_diff_parts)
