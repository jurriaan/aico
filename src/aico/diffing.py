import difflib
import re
from pathlib import Path

from aico.models import AIPatch


def _try_exact_string_patch(
    original_content: str, search_block: str, replace_block: str
) -> str | None:
    # Handle file creation
    if not search_block and not original_content:
        return replace_block

    # Handle file deletion
    if not replace_block and search_block == original_content:
        return ""

    count = original_content.count(search_block)
    if count != 1:
        # Block not found (count=0) or is ambiguous (count>1).
        # Fall back to the flexible patcher for more detailed analysis.
        return None

    # Use replace with a count of 1. At this point, we know there's exactly one occurrence.
    return original_content.replace(search_block, replace_block, 1)


def _get_consistent_indentation(lines: list[str]) -> str:
    for line in lines:
        if line.strip():
            return line[: len(line) - len(line.lstrip())]
    return ""


def _try_whitespace_flexible_patch(
    original_content: str, search_block: str, replace_block: str
) -> str | None:
    original_lines = original_content.splitlines(keepends=True)
    search_lines = search_block.splitlines(keepends=True)
    replace_lines = replace_block.splitlines(keepends=True)

    if not search_lines:
        return None

    # Strip both leading and trailing whitespace for comparison to handle
    # potential missing newlines from the LLM/parser.
    stripped_search_lines = [line.strip() for line in search_lines]

    matching_block_start_indices = []
    for i in range(len(original_lines) - len(search_lines) + 1):
        original_lines_chunk = original_lines[i : i + len(search_lines)]
        stripped_original_lines_chunk = [line.strip() for line in original_lines_chunk]

        if stripped_original_lines_chunk == stripped_search_lines:
            matching_block_start_indices.append(i)

    if len(matching_block_start_indices) > 1:
        return "AMBIGUOUS_PATCH"
    if not matching_block_start_indices:
        return None

    match_start_index = matching_block_start_indices[0]
    matched_original_lines_chunk = original_lines[
        match_start_index : match_start_index + len(search_lines)
    ]

    original_anchor_indent = _get_consistent_indentation(matched_original_lines_chunk)
    replace_min_indent = _get_consistent_indentation(replace_lines)

    indented_replace_lines = []
    for line in replace_lines:
        if not line.strip():
            indented_replace_lines.append(line)
            continue

        # Strip the replace block's own base indentation.
        relative_line = line
        if line.startswith(replace_min_indent):
            relative_line = line[len(replace_min_indent) :]

        # Apply the original anchor indentation.
        new_line = original_anchor_indent + relative_line
        indented_replace_lines.append(new_line)

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
    exact_patch = _try_exact_string_patch(original_content, search_block, replace_block)
    if exact_patch is not None:
        return exact_patch

    # Stage 2: Whitespace-insensitive match
    flexible_patch = _try_whitespace_flexible_patch(
        original_content, search_block, replace_block
    )
    if flexible_patch is not None:
        return flexible_patch

    return None


def _find_best_matching_filename(
    llm_path: str, available_paths: list[str]
) -> str | None:
    # 1. Exact Match
    if llm_path in available_paths:
        return llm_path

    # 2. Basename Match
    llm_basename = Path(llm_path).name
    basename_matches = [
        path for path in available_paths if Path(path).name == llm_basename
    ]
    if len(basename_matches) == 1:
        return basename_matches[0]
    if len(basename_matches) > 1:
        return "AMBIGUOUS_FILE"

    # 3. Fuzzy match
    close_matches = difflib.get_close_matches(
        llm_path, available_paths, n=1, cutoff=0.8
    )
    if close_matches:
        return close_matches[0]

    return None


def _parse_llm_edit_block(block_text: str) -> AIPatch | None:
    header_match = re.match(r"File: (.*?)\n", block_text)
    if not header_match:
        return None

    llm_file_path = header_match.group(1).strip()

    # Anchor the regex to the end of the string (`$`) to prevent a
    # delimiter in the content from being treated as the end of the block.
    search_replace_match = re.search(
        r"<<<<<<< SEARCH\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE$",
        block_text,
        re.DOTALL,
    )

    if not search_replace_match:
        return None

    search_content = search_replace_match.group(1)
    replace_content = search_replace_match.group(2)

    return AIPatch(
        llm_file_path=llm_file_path,
        search_content=search_content,
        replace_content=replace_content,
    )


def _create_ambiguous_file_error_diff(llm_path: str) -> str:
    return (
        f"--- a/{llm_path} (ambiguous match)\n"
        f"+++ b/{llm_path} (ambiguous match)\n"
        f"@@ -1 +2 @@\n"
        f"-Error: The file path '{llm_path}' is ambiguous and matches multiple files in the context.\n"
        f"+Please provide a more specific path and try again."
    )


def _create_file_not_found_error_diff(llm_path: str) -> str:
    return (
        f"--- a/{llm_path} (not found)\n"
        f"+++ b/{llm_path} (not found)\n"
        f"@@ -1 +2 @@\n"
        f"-Error: The file path '{llm_path}' from the AI does not match any file in the context.\n"
        f"+Skipping this block."
    )


def _create_patch_failed_error_diff(
    file_path: str, search_block: str, original_content: str
) -> str:
    error_message_lines: list[str] = [
        f"Error: The SEARCH block from the AI could not be found in '{file_path}'.\n",
        "This can happen if the file has changed, or if the AI made a mistake.\n",
    ]

    # Find best match for context to show the user
    original_lines = original_content.splitlines()
    search_lines = search_block.splitlines()

    if search_lines:
        matcher = difflib.SequenceMatcher(
            None, original_lines, search_lines, autojunk=False
        )
        match = matcher.find_longest_match(
            0, len(original_lines), 0, len(search_lines)
        )

        # Only show context if a reasonable portion of the search block was matched.
        is_significant_match = (
            match.size > 0 and (match.size / len(search_lines)) > 0.5
        )
        if is_significant_match:
            error_message_lines.extend(
                [
                    f"\nThe AI may have been targeting the code found near line {match.a + 1}:\n",
                    "--- CONTEXT FROM ORIGINAL FILE ---\n",
                ]
            )

            context_radius = 2
            start = max(0, match.a - context_radius)
            end = min(len(original_lines), match.a + match.size + context_radius)

            for i, line in enumerate(original_lines[start:end], start=start):
                prefix = "  "
                if match.a <= i < match.a + match.size:
                    prefix = "> "
                error_message_lines.append(f"{i + 1:4d}{prefix}{line}\n")
            error_message_lines.append("--- END CONTEXT ---\n")

    error_message_lines.extend(
        [
            "\nThe AI provided the following SEARCH block:\n",
            "--- SEARCH BLOCK ---\n",
        ]
        + [line + "\n" for line in search_block.splitlines()]
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


def _create_ambiguous_patch_error_diff(file_path: str) -> str:
    error_message_lines = [
        f"Error: The SEARCH block is ambiguous and was found multiple times in the file '{file_path}'.\n",
        "Please provide a more specific SEARCH block that uniquely identifies the target code.",
    ]
    return "".join(
        difflib.unified_diff(
            [],
            error_message_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path} (patch failed)",
        )
    )


def _generate_diff_for_single_block(
    parsed_block: AIPatch, original_file_contents: dict[str, str]
) -> str:
    search_content = parsed_block.search_content

    file_path = _find_best_matching_filename(
        parsed_block.llm_file_path, list(original_file_contents.keys())
    )

    if file_path == "AMBIGUOUS_FILE":
        return _create_ambiguous_file_error_diff(parsed_block.llm_file_path)

    if file_path:
        original_content = original_file_contents[file_path]
    elif search_content == "":
        # This is a valid new file creation
        file_path = parsed_block.llm_file_path
        original_content = ""
    else:
        # The file was not found, and it's not a new file instruction.
        return _create_file_not_found_error_diff(parsed_block.llm_file_path)

    new_content_full = _create_patched_content(
        original_content, parsed_block.search_content, parsed_block.replace_content
    )

    if new_content_full is None:
        return _create_patch_failed_error_diff(
            file_path, search_content, original_content
        )

    if new_content_full == "AMBIGUOUS_PATCH":
        return _create_ambiguous_patch_error_diff(file_path)

    # Happy path: successful patch
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
