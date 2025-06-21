import difflib
from collections.abc import Iterator
from pathlib import Path

import regex as re

from aico.models import AIPatch, ProcessedDiffBlock

# This regex is the core of the parser. It finds a complete `File:` block.
# It uses named capture groups and backreferences to be robust.
#
# - `(?P<indent> *)`: Captures the leading indentation of the `<<<<<<<` line.
# - `(?P<search_content>.*?)`: Non-greedily captures the search content.
# - `\n(?P=indent)=======`: Uses a backreference `(?P=indent)` to ensure the `=======`
#   delimiter has the same indentation as the opening delimiter.
# - `\s*$`: Allows for trailing whitespace on the final `>>>>>>> REPLACE` line.
# - `re.DOTALL`: Allows `.` to match newlines, so the content blocks can be multiline.
# - `re.MULTILINE`: Allows `^` and `$` to match the start/end of lines, not just the string.
_FILE_BLOCK_REGEX = re.compile(
    r"^File: (.*?)\n"
    r"(?P<block>"
    r"^(?P<indent> *)<<<<<<< SEARCH\n"
    r"(?P<search_content>.*?)"
    r"^(?P=indent)=======\n"  # <-- The ^ anchors this to the start of a line
    r"(?P<replace_content>.*?)"
    r"^(?P=indent)>>>>>>> REPLACE\s*$"  # <-- Same here
    r")",
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
    if not any(stripped_search_lines):
        # A search block containing only whitespace is ambiguous and not supported
        # for flexible patching. The exact patcher should handle it if it's an exact match.
        return None

    matching_block_start_indices: list[int] = []
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

    indented_replace_lines: list[str] = []
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


def _create_aipatch_from_match(match: re.Match[str]) -> AIPatch:
    """Helper to create an AIPatch from a regex match object."""
    return AIPatch(
        llm_file_path=match.group(1).strip(),
        search_content=match.group("search_content").rstrip(),
        replace_content=match.group("replace_content").rstrip(),
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


def _process_llm_response_stream(
    original_file_contents: dict[str, str], llm_response: str
) -> Iterator[str | ProcessedDiffBlock]:
    """
    Parses an LLM response, processes diff blocks sequentially, and yields results.

    This generator is the core stateful engine. It maintains the "current" state
    of file contents as it iterates through diff blocks, ensuring that each
    patch is applied against the result of the previous one for the same file.

    Yields:
        Either a string (for conversational text) or a ProcessedDiffBlock.
    """
    current_file_contents = original_file_contents.copy()
    last_end = 0
    matches = list(_FILE_BLOCK_REGEX.finditer(llm_response))

    if not matches:
        if llm_response:
            yield llm_response
        return

    for match in matches:
        # 1. Yield any conversational text that appeared before this block
        if match.start() > last_end:
            yield llm_response[last_end : match.start()]
        last_end = match.end()

        # 2. Process the found `File:` block
        parsed_block = _create_aipatch_from_match(match)
        search_content = parsed_block.search_content
        diff_string: str

        # Find file path first. Handle file path errors immediately.
        actual_file_path = _find_best_matching_filename(
            parsed_block.llm_file_path, list(current_file_contents.keys())
        )

        if actual_file_path == "AMBIGUOUS_FILE":
            diff_string = _create_ambiguous_file_error_diff(parsed_block.llm_file_path)
            yield ProcessedDiffBlock(
                llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string
            )
            continue

        # Determine if this is a new file vs. existing file vs. file not found.
        content_before_patch: str
        is_new_file = False
        if actual_file_path:
            content_before_patch = current_file_contents[actual_file_path]
        elif (
            search_content == ""
            and parsed_block.llm_file_path not in current_file_contents
        ):
            actual_file_path = parsed_block.llm_file_path
            content_before_patch = ""
            is_new_file = True
        else:
            # If the search content is not empty, but we couldn't find a file, it's an error.
            if not actual_file_path:
                diff_string = _create_file_not_found_error_diff(
                    parsed_block.llm_file_path
                )
                yield ProcessedDiffBlock(
                    llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string
                )
                continue
            # This case should now be rare, but handles if an empty search block is
            # provided for a file that already exists in the context. We treat it as
            # a patch against the existing content.
            content_before_patch = current_file_contents.get(actual_file_path, "")

        # Now we have a valid file path and content. Apply the patch.
        new_content_full = _create_patched_content(
            content_before_patch,
            search_content,
            parsed_block.replace_content,
        )

        if new_content_full is None:
            diff_string = _create_patch_failed_error_diff(
                actual_file_path, search_content, content_before_patch
            )
        elif new_content_full == "AMBIGUOUS_PATCH":
            diff_string = _create_ambiguous_patch_error_diff(actual_file_path)
        else:
            # --- Success Path ---
            from_file = f"a/{actual_file_path}"
            to_file = f"b/{actual_file_path}"
            if is_new_file:
                from_file = "/dev/null"
            elif not new_content_full:  # File deletion
                to_file = "/dev/null"

            diff_lines = list(
                difflib.unified_diff(
                    content_before_patch.splitlines(keepends=True),
                    new_content_full.splitlines(keepends=True),
                    fromfile=from_file,
                    tofile=to_file,
                )
            )
            diff_string = "".join(diff_lines)

            # Update state for the next iteration
            if not new_content_full and actual_file_path in current_file_contents:
                del current_file_contents[actual_file_path]
            else:
                current_file_contents[actual_file_path] = new_content_full

        # 3. Yield the processed block result
        yield ProcessedDiffBlock(
            llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string
        )

    # 4. Yield any remaining conversational text after the last block
    if last_end < len(llm_response):
        yield llm_response[last_end:]


def generate_unified_diff(
    original_file_contents: dict[str, str], llm_response: str
) -> str:
    """
    Generates a unified diff string by processing all `File:` blocks sequentially.
    Conversational text is ignored.
    """
    diff_parts: list[str] = []
    stream = _process_llm_response_stream(original_file_contents, llm_response)

    for item in stream:
        match item:
            case ProcessedDiffBlock(unified_diff=diff_string):
                diff_parts.append(diff_string)
            case str():
                # Ignore conversational text for the unified diff
                pass

    return "".join(diff_parts).strip()


def generate_display_content(
    original_file_contents: dict[str, str], llm_response: str
) -> str:
    """
    Generates a markdown-formatted string with diffs embedded in conversational text.
    Processes all `File:` blocks sequentially.
    """
    processed_parts: list[str] = []
    stream = _process_llm_response_stream(original_file_contents, llm_response)

    for item in stream:
        match item:
            case str() as text:
                processed_parts.append(text)
            case ProcessedDiffBlock(
                llm_file_path=llm_file_path, unified_diff=diff_string
            ):
                markdown_diff = (
                    f"File: {llm_file_path}\n```diff\n{diff_string.strip()}\n```\n"
                )
                processed_parts.append(markdown_diff)

    return "".join(processed_parts)
