import difflib
from pathlib import Path

import regex as re

from aico.models import AIPatch

# This single regex is the core of the parser. It finds a complete `File:` block
# that contains a valid SEARCH/REPLACE block.
_FILE_BLOCK_REGEX = re.compile(
    r"^File: (.*?)\n(^ *<<<<<<< SEARCH\n(.*?)\s*=======\n\s*(.*?)\s*>>>>>>> REPLACE\s*$)",
    re.MULTILINE | re.DOTALL | re.UNICODE,
)


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


def _create_aipatch_from_match(match: re.Match) -> AIPatch:
    """Helper to create an AIPatch from a regex match object."""
    return AIPatch(
        llm_file_path=match.group(1).strip(),
        search_content=match.group(3),
        replace_content=match.group(4),
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
        match = matcher.find_longest_match(0, len(original_lines), 0, len(search_lines))

        # Only show context if a reasonable portion of the search block was matched.
        is_significant_match = match.size > 0 and (match.size / len(search_lines)) > 0.5
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


def generate_unified_diff(
    original_file_contents: dict[str, str], llm_response: str
) -> str:
    unified_diff_parts = []
    matches = _FILE_BLOCK_REGEX.finditer(llm_response)

    for match in matches:
        parsed_block = _create_aipatch_from_match(match)
        diff_for_block = _generate_diff_for_single_block(
            parsed_block, original_file_contents
        )
        unified_diff_parts.append(diff_for_block)

    # Malformed blocks or conversational text are ignored, so if no matches are found,
    # an empty string is returned, which is the correct behavior.
    return "".join(unified_diff_parts)


def generate_display_content(
    original_file_contents: dict[str, str], llm_response: str
) -> str:
    processed_parts = []
    last_end = 0
    matches = list(_FILE_BLOCK_REGEX.finditer(llm_response))

    if not matches:
        return llm_response

    for match in matches:
        # Append the conversational text before this `File:` block
        processed_parts.append(llm_response[last_end : match.start()])

        # Process the found `File:` block
        parsed_block = _create_aipatch_from_match(match)
        diff_string = _generate_diff_for_single_block(
            parsed_block, original_file_contents
        )
        # Create the markdown block, keeping the File: header from the original text
        markdown_diff = (
            f"File: {parsed_block.llm_file_path}\n```diff\n{diff_string.strip()}\n```\n"
        )
        processed_parts.append(markdown_diff)

        last_end = match.end()

    # Append any remaining conversational text after the last `File:` block
    processed_parts.append(llm_response[last_end:])

    return "".join(processed_parts)
