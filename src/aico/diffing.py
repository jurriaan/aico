import difflib
from collections.abc import Callable, Iterator
from pathlib import Path

import regex as re

from aico.models import (
    AIPatch,
    FileContents,
    ProcessedDiffBlock,
    StreamYieldItem,
    WarningMessage,
)

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
    r"File: (?P<file_path>.*?)\n"
    + r"(?P<block>"
    + r"^(?P<indent>\p{H}*)<<<<<<< SEARCH\n"
    + r"(?P<search_content>.*?)"
    + r"^(?P=indent)=======\n"  # <-- The ^ anchors this to the start of a line
    + r"(?P<replace_content>.*?)"
    + r"^(?P=indent)>>>>>>> REPLACE\s*$"  # <-- Same here
    + r")",
    re.MULTILINE | re.DOTALL | re.UNICODE,
)

# This regex checks for a File: line followed by a SEARCH delimiter at the end of the text.
# It's more robust than simple string checking.
_IN_PROGRESS_BLOCK_REGEX = re.compile(
    r"File: .*?^(\p{H}*)<<<<<<< SEARCH.*$",
    re.MULTILINE | re.DOTALL | re.UNICODE,
)


def _try_exact_string_patch(original_content: str, search_block: str, replace_block: str) -> str | None:
    # Handle file creation
    if not search_block and not original_content:
        return replace_block

    # Handle file deletion
    if not replace_block and search_block == original_content:
        return ""

    # An empty or whitespace-only search block is only valid for whole-file operations
    # (new file or full replacement), which are handled above. For a partial patch
    # on an existing file, it's invalid.
    if not search_block.strip():
        return None

    if search_block not in original_content:
        # Block not found. Fall back to the flexible patcher.
        return None

    # Use replace with a count of 1 to replace only the first occurrence.
    return original_content.replace(search_block, replace_block, 1)


def _get_consistent_indentation(lines: list[str]) -> str:
    for line in lines:
        if line.strip():
            return line[: len(line) - len(line.lstrip())]
    return ""


def _try_whitespace_flexible_patch(original_content: str, search_block: str, replace_block: str) -> str | None:
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

    if not matching_block_start_indices:
        return None

    # If there are multiple matches, we now default to patching the first one.
    match_start_index = matching_block_start_indices[0]
    matched_original_lines_chunk = original_lines[match_start_index : match_start_index + len(search_lines)]

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


def _create_patched_content(original_content: str, search_block: str, replace_block: str) -> str | None:
    # Stage 1: Exact match
    exact_patch = _try_exact_string_patch(original_content, search_block, replace_block)
    if exact_patch is not None:
        return exact_patch

    # Stage 2: Whitespace-insensitive match
    flexible_patch = _try_whitespace_flexible_patch(original_content, search_block, replace_block)
    if flexible_patch is not None:
        return flexible_patch

    return None


def _resolve_file_path(
    patch: AIPatch, file_contents: dict[str, str], session_root: Path
) -> tuple[str | None, str | None]:
    """
    Resolves the file path from an AI patch using a hierarchical strategy.

    1.  Exact match in context.
    2.  New file intent (empty search block).
    3.  Filesystem fallback (file exists on disk but not in context).
    4.  Failure.

    Returns a tuple of (resolved_path, warning_message).
    If a file is found on disk, it's added to the `file_contents` dict.
    """
    # 1. Exact Match
    if patch.llm_file_path in file_contents:
        return patch.llm_file_path, None

    # 2. New file intent (empty or whitespace-only search block)
    if not patch.search_content.strip():
        return patch.llm_file_path, None

    # 3. Filesystem Fallback
    disk_path = session_root / patch.llm_file_path
    if disk_path.is_file():
        # Read content and add to in-memory context for this session
        content = disk_path.read_text()
        file_contents[patch.llm_file_path] = content

        warning = (
            f"Warning: '{patch.llm_file_path}' was not in the session context but was found on disk. "
            "Consider adding it to the session."
        )
        return patch.llm_file_path, warning

    # 4. Failure
    return None, None


def _create_aipatch_from_match(match: re.Match[str]) -> AIPatch:
    """Helper to create an AIPatch from a regex match object."""
    return AIPatch(
        llm_file_path=match.group("file_path").strip(),
        search_content=match.group("search_content"),
        replace_content=match.group("replace_content"),
    )


def _create_file_not_found_error_diff(llm_path: str) -> str:
    return (
        f"--- a/{llm_path} (not found)\n"
        f"+++ b/{llm_path} (not found)\n"
        f"@@ -1 +2 @@\n"
        f"-Error: The file path '{llm_path}' from the AI does not match any file in the context.\n"
        f"+Skipping this block."
    )


def _create_patch_failed_error_diff(file_path: str, search_block: str, original_content: str) -> str:
    error_message_lines: list[str] = [
        f"Error: The SEARCH block from the AI could not be found in '{file_path}'.\n",
        "This can happen if the file has changed, or if the AI made a mistake.\n",
    ]

    # Find best match for context to show the user
    original_lines = original_content.splitlines()
    search_lines = search_block.splitlines()

    if search_lines:
        matcher = difflib.SequenceMatcher(None, original_lines, search_lines, autojunk=False)
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


def parse_live_render_segments(llm_response: str) -> Iterator[tuple[str, str]]:
    """
    Parses the full LLM response buffer and yields tuples of (type, content).
    Types can be 'conversation', 'complete_diff', or 'in_progress_diff'.
    """
    last_end = 0
    # Use the existing _FILE_BLOCK_REGEX to find all *complete* blocks first.
    complete_matches = list(_FILE_BLOCK_REGEX.finditer(llm_response))

    for match in complete_matches:
        # Yield conversational text that appears before a complete block.
        if match.start() > last_end:
            yield ("conversation", llm_response[last_end : match.start()])

        # Yield the complete, parseable block.
        yield ("complete_diff", match.group(0))
        last_end = match.end()

    # Get any text remaining after the last complete block.
    remaining_text = llm_response[last_end:]

    # Use the new, more precise regex to check if the remaining text looks like the beginning of a diff block.
    if remaining_text and _IN_PROGRESS_BLOCK_REGEX.search(remaining_text):
        yield ("in_progress_diff", remaining_text)
    elif remaining_text:
        yield ("conversation", remaining_text)


def _process_single_diff_block(
    parsed_block: AIPatch,
    current_file_contents: dict[str, str],
    original_file_contents: FileContents,
    session_root: Path,
) -> tuple[ProcessedDiffBlock, WarningMessage | None]:
    """Processes a single parsed AIPatch block and returns the resulting diff and any warnings."""
    diff_string: str
    actual_file_path, warning_text = _resolve_file_path(parsed_block, current_file_contents, session_root)
    warning_message = WarningMessage(text=warning_text) if warning_text else None

    if actual_file_path is None:
        # The 'warning' from resolve_file_path is None when path is not found. So `warning_message` here is also None.
        diff_string = _create_file_not_found_error_diff(parsed_block.llm_file_path)
        return ProcessedDiffBlock(llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string), warning_message

    is_new_file = (actual_file_path not in original_file_contents) and (warning_message is None)
    content_before_patch = current_file_contents.get(actual_file_path, "")

    search_content = parsed_block.search_content
    new_content_full = _create_patched_content(
        content_before_patch,
        search_content,
        parsed_block.replace_content,
    )

    if new_content_full is None:
        diff_string = _create_patch_failed_error_diff(actual_file_path, search_content, content_before_patch)
    elif is_new_file and not new_content_full:
        # Handle the edge case where a new file is created empty.
        # difflib.unified_diff returns an empty string for this case, so we must construct the diff header manually.
        diff_string = f"--- /dev/null\n+++ b/{actual_file_path}\n"
        current_file_contents[actual_file_path] = new_content_full
    else:
        from_file = f"a/{actual_file_path}"
        to_file = f"b/{actual_file_path}"
        if is_new_file:
            from_file = "/dev/null"
        elif not new_content_full:
            to_file = "/dev/null"

        diff_lines = list(
            difflib.unified_diff(
                content_before_patch.splitlines(keepends=True),
                new_content_full.splitlines(keepends=True),
                fromfile=from_file,
                tofile=to_file,
            )
        )

        if diff_lines and not content_before_patch.endswith("\n") and content_before_patch:
            for i, line in reversed(list(enumerate(diff_lines))):
                if line.startswith(("-", " ")) and i > 2:
                    diff_lines.insert(i + 1, "\n\\ No newline at end of file\n")
                    break

        diff_string = "".join(diff_lines)

        # This function mutates the state of `current_file_contents` for the main processor loop.
        if not new_content_full and actual_file_path in current_file_contents:
            del current_file_contents[actual_file_path]
        else:
            current_file_contents[actual_file_path] = new_content_full

    return ProcessedDiffBlock(llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string), warning_message


def process_llm_response_stream(
    original_file_contents: FileContents, llm_response: str, session_root: Path
) -> Iterator[StreamYieldItem]:
    """
    Parses an LLM response, processes diff blocks sequentially, and yields results.

    This generator is the core stateful engine. It maintains the "current" state
    of file contents as it iterates through diff blocks, ensuring that each

    patch is applied against the result of the previous one for the same file.

    Yields:
        Either a string (for conversational text), a ProcessedDiffBlock, or a WarningMessage.
    """
    current_file_contents = dict(original_file_contents)
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
        processed_block, warning = _process_single_diff_block(
            parsed_block, current_file_contents, original_file_contents, session_root
        )

        if warning:
            yield warning

        yield processed_block

    # 3. Yield any remaining conversational text after the last block
    if last_end < len(llm_response):
        yield llm_response[last_end:]


def _generate_output_from_stream(
    original_file_contents: FileContents,
    llm_response: str,
    session_root: Path,
    formatter: Callable[[StreamYieldItem], str],
) -> str:
    output_parts: list[str] = []
    # Make a copy because the stream processor modifies it in-place
    stream = process_llm_response_stream(dict(original_file_contents), llm_response, session_root)

    for item in stream:
        output_parts.append(formatter(item))

    return "".join(output_parts)


def generate_unified_diff(original_file_contents: FileContents, llm_response: str, session_root: Path) -> str:
    """
    Generates a unified diff string by processing all `File:` blocks sequentially.
    Conversational text and warnings are ignored.
    """

    def formatter(item: StreamYieldItem) -> str:
        match item:
            case ProcessedDiffBlock(unified_diff=diff_string):
                return diff_string
            case WarningMessage():
                return ""
            case str():
                return ""

    return _generate_output_from_stream(original_file_contents, llm_response, session_root, formatter)


def generate_display_content(original_file_contents: FileContents, llm_response: str, session_root: Path) -> str:
    """
    Generates a markdown-formatted string with diffs embedded in conversational text.
    Processes all `File:` blocks sequentially. Warnings are ignored.
    """

    def formatter(item: StreamYieldItem) -> str:
        match item:
            case str() as text:
                return text
            case ProcessedDiffBlock(llm_file_path=llm_file_path, unified_diff=diff_string):
                return f"File: `{llm_file_path}`\n```diff\n{diff_string.strip()}\n```\n"
            case WarningMessage():
                return ""

    return _generate_output_from_stream(original_file_contents, llm_response, session_root, formatter)
