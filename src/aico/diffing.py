import difflib
from collections.abc import Iterator
from pathlib import Path

import regex as re

from aico.models import (
    AIPatch,
    FileContents,
    ProcessedDiffBlock,
    ProcessedPatchResult,
    ResolvedFilePath,
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
_FILE_HEADER_REGEX = re.compile(r"(^\p{H}*File: .*?\n)", re.MULTILINE | re.UNICODE)

# This regex is the core of the parser for individual SEARCH/REPLACE blocks.
# It no longer includes the "File:" header.
_FILE_BLOCK_REGEX = re.compile(
    r"(?P<block>"
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


def _add_no_newline_marker_if_needed(diff_lines: list[str], original_content: str | None) -> None:
    """
    Manually injects the '\\ No newline at end of file' marker into a diff list IN-PLACE.
    This is a workaround because `difflib` doesn't add the marker itself when using
    `splitlines(keepends=True)`, which is necessary to handle files with significant blank lines.

    It also ensures the line preceding the marker correctly ends with a newline, as `difflib`
    omits it for the last line of a file that lacks a trailing newline.
    """
    if not (diff_lines and original_content and not original_content.endswith("\n")):
        return

    # Find the last line in the diff hunk that originates from the "from" file.
    # These lines start with ' ' (context) or '-' (deletion).
    # We iterate backwards from the end of the diff list.
    for i in range(len(diff_lines) - 1, 1, -1):  # Stop after headers at index 1
        line = diff_lines[i]
        if line.startswith("-") or line.startswith(" "):
            # This is the last relevant line from the original file.
            # If difflib's output for this line lacks a newline, add one.
            if not diff_lines[i].endswith("\n"):
                diff_lines[i] += "\n"

            # Insert the marker immediately after this line.
            diff_lines.insert(i + 1, "\\ No newline at end of file\n")
            return


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
    patch: AIPatch,
    current_file_contents: dict[str, str],
    session_root: Path,
) -> ResolvedFilePath:
    """
    Resolves the file path from an AI patch, returning the content if found via fallback.

    This function is now side-effect free. It no longer mutates dictionaries.

    1.  Exact match in the current set of files being processed.
    2.  New file intent (empty search block).
    3.  Filesystem fallback (file exists on disk but not in context).
    4.  Failure.
    """
    # 1. Exact Match in current working set
    if patch.llm_file_path in current_file_contents:
        return ResolvedFilePath(path=patch.llm_file_path, warning=None, fallback_content=None)

    # 2. New file intent (empty or whitespace-only search block)
    if not patch.search_content.strip():
        return ResolvedFilePath(path=patch.llm_file_path, warning=None, fallback_content=None)

    # 3. Filesystem Fallback
    disk_path = session_root / patch.llm_file_path
    if disk_path.is_file():
        content = disk_path.read_text()
        warning = (
            f"Warning: '{patch.llm_file_path}' was not in the session context but was found on disk. "
            "Consider adding it to the session."
        )
        return ResolvedFilePath(path=patch.llm_file_path, warning=warning, fallback_content=content)

    # 4. Failure
    return ResolvedFilePath(path=None, warning=None, fallback_content=None)


def _create_aipatch_from_match(match: re.Match[str], llm_file_path: str) -> AIPatch:
    """Helper to create an AIPatch from a regex match object."""
    return AIPatch(
        llm_file_path=llm_file_path,
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
    # We now need a regex that includes the file header to correctly segment for rendering.
    # This is different from the main parser which splits by header first.
    rendering_block_regex = re.compile(
        r"File: .*?\n" + _FILE_BLOCK_REGEX.pattern, re.MULTILINE | re.DOTALL | re.UNICODE
    )
    complete_matches = list(rendering_block_regex.finditer(llm_response))

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
    content_before_patch: str,
    is_new_file: bool,
    actual_file_path: str,
) -> ProcessedPatchResult:
    """
    Processes a single parsed AIPatch block and returns the resulting content and diff block.

    This is now a PURE function. It does not perform I/O or mutate external state.
    """
    diff_string: str
    search_content = parsed_block.search_content
    new_content_full = _create_patched_content(
        content_before_patch,
        search_content,
        parsed_block.replace_content,
    )

    if new_content_full is None:
        diff_string = _create_patch_failed_error_diff(actual_file_path, search_content, content_before_patch)
        return ProcessedPatchResult(
            new_content=None,
            diff_block=ProcessedDiffBlock(llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string),
        )

    if is_new_file and not new_content_full:
        # Handle the edge case where a new file is created empty.
        # difflib.unified_diff returns an empty string for this case, so we must construct the diff header manually.
        diff_string = f"--- /dev/null\n+++ b/{actual_file_path}\n"
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
        _add_no_newline_marker_if_needed(diff_lines, content_before_patch)

        diff_string = "".join(diff_lines)

    return ProcessedPatchResult(
        new_content=new_content_full,
        diff_block=ProcessedDiffBlock(llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string),
    )


def _apply_patches(
    original_file_contents: FileContents, llm_response: str, session_root: Path
) -> tuple[dict[str, str], dict[str, str], list[WarningMessage]]:
    """
    Applies all patches from an LLM response to calculate the final state of files.

    This function does not generate diffs. Its only purpose is to compute the
    "after" state of all files by sequentially applying every valid patch.
    It handles filesystem fallbacks and updates the original content mapping
    to ensure final diffs are generated correctly.

    Returns:
        A tuple containing:
        - The final file contents dictionary.
        - The original file contents, updated with any filesystem fallbacks.
        - A list of any warnings that were generated.
    """
    final_contents = dict(original_file_contents)
    warnings: list[WarningMessage] = []

    # This is a bit tricky: `original_file_contents` is a Mapping (immutable view),
    # but when a file is found via fallback, we need to add it to the "original"
    # set to generate the correct final diff. We use a mutable copy for this.
    original_contents_mutable = dict(original_file_contents)

    chunks = _FILE_HEADER_REGEX.split(llm_response)
    _ = chunks.pop(0)  # Discard initial conversational text

    for i in range(0, len(chunks), 2):
        header_line = chunks[i]
        content = chunks[i + 1] if (i + 1) < len(chunks) else ""
        llm_file_path = header_line.strip().removeprefix("File:").strip()

        for match in _FILE_BLOCK_REGEX.finditer(content):
            parsed_block = _create_aipatch_from_match(match, llm_file_path)

            resolution = _resolve_file_path(parsed_block, final_contents, session_root)
            if resolution.warning:
                warnings.append(WarningMessage(text=resolution.warning))

            if resolution.path is None:
                continue

            actual_file_path = resolution.path
            if resolution.fallback_content is not None:
                final_contents[actual_file_path] = resolution.fallback_content
                original_contents_mutable[actual_file_path] = resolution.fallback_content

            is_new_file = actual_file_path not in original_contents_mutable
            content_before_patch = final_contents.get(actual_file_path, "")

            result = _process_single_diff_block(parsed_block, content_before_patch, is_new_file, actual_file_path)

            if result.new_content is not None:
                if not result.new_content and actual_file_path in final_contents:
                    del final_contents[actual_file_path]
                else:
                    final_contents[actual_file_path] = result.new_content

    return final_contents, original_contents_mutable, warnings


def process_llm_response_stream(
    original_file_contents: FileContents,
    llm_response: str,
    session_root: Path,
) -> Iterator[StreamYieldItem]:
    """
    Parses an LLM response, processes diff blocks sequentially, and yields results.

    This generator is the core stateful engine for generating display content.
    It encapsulates its own state, creating a temporary copy of file contents
    to ensure that each patch for a given file is applied against the result
    of the previous one.

    Args:
        original_file_contents: An immutable mapping of the original file contents.
        llm_response: The raw response from the language model.
        session_root: The root path of the session.

    Yields:
        Either a string (for conversational text), a ProcessedDiffBlock, or a WarningMessage.
    """
    current_file_contents = dict(original_file_contents)
    original_contents_for_diffing = dict(original_file_contents)

    chunks = _FILE_HEADER_REGEX.split(llm_response)
    initial_convo = chunks.pop(0)
    if initial_convo:
        yield initial_convo

    for i in range(0, len(chunks), 2):
        header_line = chunks[i]
        content = chunks[i + 1] if (i + 1) < len(chunks) else ""
        llm_file_path = header_line.strip().removeprefix("File:").strip()
        last_end = 0
        matches = list(_FILE_BLOCK_REGEX.finditer(content))

        if not matches:
            yield header_line + content
            continue

        for match in matches:
            if match.start() > last_end:
                yield content[last_end : match.start()]
            last_end = match.end()

            parsed_block = _create_aipatch_from_match(match, llm_file_path)
            resolution = _resolve_file_path(parsed_block, current_file_contents, session_root)

            if resolution.warning:
                yield WarningMessage(text=resolution.warning)

            if resolution.path is None:
                diff_string = _create_file_not_found_error_diff(parsed_block.llm_file_path)
                yield ProcessedDiffBlock(llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string)
                continue

            actual_file_path = resolution.path
            if resolution.fallback_content is not None:
                current_file_contents[actual_file_path] = resolution.fallback_content
                original_contents_for_diffing[actual_file_path] = resolution.fallback_content

            is_new_file = actual_file_path not in original_contents_for_diffing
            content_before_patch = current_file_contents.get(actual_file_path, "")
            result = _process_single_diff_block(parsed_block, content_before_patch, is_new_file, actual_file_path)

            if result.new_content is not None:
                if not result.new_content and actual_file_path in current_file_contents:
                    del current_file_contents[actual_file_path]
                else:
                    current_file_contents[actual_file_path] = result.new_content

            yield result.diff_block

        if last_end < len(content):
            yield content[last_end:]


def generate_unified_diff(original_file_contents: FileContents, llm_response: str, session_root: Path) -> str:
    """
    Generates a unified diff string by processing all `File:` blocks sequentially.
    On success with multiple patches for a single file, it generates a single compound diff.
    On failure, it returns incremental diffs to show the error message.
    """
    # Run the stream processor once to get the incremental diffs and check for errors.
    # This is necessary because if a patch fails, we need to show the error in context.
    incremental_blocks: list[ProcessedDiffBlock] = []
    has_errors = False
    stream_results = process_llm_response_stream(original_file_contents, llm_response, session_root)

    for item in stream_results:
        if isinstance(item, ProcessedDiffBlock):
            incremental_blocks.append(item)
            if "patch failed" in item.unified_diff or "not found" in item.unified_diff:
                has_errors = True

    # If any patches failed, return the concatenated incremental diffs, which will show the error messages.
    if has_errors:
        return "".join(block.unified_diff for block in incremental_blocks)

    # If all patches succeeded, calculate the final state and compose a single clean diff.
    final_contents, original_contents_updated, _ = _apply_patches(original_file_contents, llm_response, session_root)
    all_diffs: list[str] = []

    # Using keys from both dicts ensures we handle file creations and deletions.
    all_files = sorted(list(set(original_contents_updated.keys()) | set(final_contents.keys())))

    for file_path in all_files:
        from_content = original_contents_updated.get(file_path)
        to_content = final_contents.get(file_path)

        if from_content == to_content:
            continue

        if from_content is None and to_content == "":
            all_diffs.append(f"--- /dev/null\n+++ b/{file_path}\n")
            continue

        from_file = f"a/{file_path}"
        to_file = f"b/{file_path}"
        if from_content is None:
            from_file = "/dev/null"
        if to_content is None:
            to_file = "/dev/null"

        from_lines = from_content.splitlines(keepends=True) if from_content is not None else []
        to_lines = to_content.splitlines(keepends=True) if to_content is not None else []

        diff_lines = list(difflib.unified_diff(from_lines, to_lines, fromfile=from_file, tofile=to_file))
        _add_no_newline_marker_if_needed(diff_lines, from_content)
        all_diffs.extend(diff_lines)

    return "".join(all_diffs)


def generate_display_content(original_file_contents: FileContents, llm_response: str, session_root: Path) -> str:
    """
    Generates a markdown-formatted string with diffs embedded in conversational text.
    Processes all `File:` blocks sequentially. Warnings are ignored.
    """
    output_parts: list[str] = []
    stream = process_llm_response_stream(original_file_contents, llm_response, session_root)

    for item in stream:
        match item:
            case str() as text:
                output_parts.append(text)
            case ProcessedDiffBlock(llm_file_path=llm_file_path, unified_diff=diff_string):
                output_parts.append(f"File: `{llm_file_path}`\n```diff\n{diff_string.strip()}\n```\n")
            case WarningMessage():
                pass  # Warnings are ignored for display content

    return "".join(output_parts)
