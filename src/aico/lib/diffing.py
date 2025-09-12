import difflib
from collections.abc import Iterator
from pathlib import Path

import regex as re

from aico.lib.models import (
    AIPatch,
    DerivedContent,
    DisplayItem,
    FileContents,
    FileHeader,
    PatchApplicationResult,
    ProcessedDiffBlock,
    ProcessedPatchResult,
    ResolvedFilePath,
    StreamYieldItem,
    UnparsedBlock,
    WarningMessage,
)
from aico.lib.session import build_original_file_contents

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

_INCOMPLETE_BLOCK_REGEX = re.compile(r"^\p{H}*<<<<<<< SEARCH", re.MULTILINE | re.UNICODE)


# This regex is the core of the parser for individual SEARCH/REPLACE blocks.
# It no longer includes the "File:" header.
_FILE_BLOCK_REGEX = re.compile(
    r"(?P<block>"
    + r"^(?P<indent>\p{H}*)<<<<<<< SEARCH\p{H}*\n"
    + r"(?P<search_content>.*?)"
    + r"^(?P=indent)=======\n"
    + r"(?P<replace_content>.*?)"
    + r"^(?P=indent)>>>>>>> REPLACE\p{H}*$"
    + r")",
    re.MULTILINE | re.DOTALL | re.UNICODE,
)

# This regex checks for a File: line followed by a SEARCH delimiter at the end of the text.
# It's more robust than simple string checking.


def _add_no_newline_marker_if_needed(diff_lines: list[str], original_content: str | None) -> None:
    """
    Manually injects the '\\ No newline at end of file' marker into a diff list IN-PLACE.
    This is a workaround because `difflib` doesn't add the marker itself when using
    `splitlines(keepends=True)`.

    The logic is: if the original file lacks a trailing newline, find the last line
    in the diff that came from the original file (' ' or '-'). If that diff line
    also lacks a trailing newline, it must be the end of the file, so we add the marker.
    """
    if not (diff_lines and original_content and not original_content.endswith("\n")):
        return

    # Iterate backwards through the diff to find the last line from the original file
    for i in range(len(diff_lines) - 1, -1, -1):
        line = diff_lines[i]

        if line.startswith("@@"):
            # We've reached the start of a hunk without finding a suitable line.
            # This means the hunk doesn't contain lines from the end of the original file.
            return

        if line.startswith("-") or line.startswith(" "):
            # This is the last relevant line from the original file within this hunk.
            # If it doesn't end with a newline, then it must be the end of the file.
            if not line.endswith("\n"):
                diff_lines[i] += "\n"
                diff_lines.insert(i + 1, "\\ No newline at end of file\n")
            # If it *does* end with a newline, the hunk is not at the end of the file,
            # so we shouldn't add a marker. In either case, we are done with this hunk.
            return


def _generate_diff_with_no_newline_handling(
    from_file: str,
    to_file: str,
    from_content: str | None,
    to_content: str | None,
) -> list[str]:
    """
    Generates a unified diff using difflib and applies custom logic to handle
    the '\\ No newline at end of file' marker, which difflib does not do correctly
    with splitlines(keepends=True).
    """
    from_lines = (from_content or "").splitlines(keepends=True)
    to_lines = (to_content or "").splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(from_lines, to_lines, fromfile=from_file, tofile=to_file))

    _add_no_newline_marker_if_needed(diff_lines, from_content)

    return diff_lines


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
    return next((line[: len(line) - len(line.lstrip())] for line in lines if line.strip()), "")


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

    matching_block_start_indices = [
        i
        for i in range(len(original_lines) - len(search_lines) + 1)
        if [line.strip() for line in original_lines[i : i + len(search_lines)]] == stripped_search_lines
    ]

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
    Resolves the canonical file path for an AI-generated patch.

    This pure function determines the correct path for a file and checks if a
    fallback to the filesystem is necessary. It follows a clear resolution order:

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
            f"File '{patch.llm_file_path}' was not in the session context but was found on disk. "
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


def _create_file_not_found_error(llm_path: str) -> str:
    return f"File '{llm_path}' from the AI does not match any file in context. Patch skipped."


def _create_patch_failed_error(file_path: str) -> str:
    error_message = (
        f"The SEARCH block from the AI could not be found in '{file_path}'. "
        f"This can happen if the file has changed or the AI made a mistake. Patch skipped."
    )
    return error_message


def _get_diff_paths(file_path: str, from_content: str | None, to_content: str | None) -> tuple[str, str]:
    """Generates the 'from' and 'to' file paths for a diff header."""
    from_file = "/dev/null" if from_content is None else f"a/{file_path}"
    to_file = "/dev/null" if to_content is None else f"b/{file_path}"
    return from_file, to_file


def _process_single_diff_block(
    parsed_block: AIPatch,
    content_before_patch: str,
    is_new_file: bool,
    actual_file_path: str,
) -> ProcessedPatchResult | None:
    """
    Processes a single parsed AIPatch block and returns the resulting content and diff block.
    Returns None if the patch cannot be applied.

    This is a pure function that does not perform I/O or mutate external state. It
    takes the "before" state and a patch, and returns the "after" state and a diff.
    """
    diff_string: str
    search_content = parsed_block.search_content
    new_content_full = _create_patched_content(
        content_before_patch,
        search_content,
        parsed_block.replace_content,
    )

    if new_content_full is None:
        return None

    if is_new_file and not new_content_full:
        # Handle the edge case where a new file is created empty.
        # difflib.unified_diff returns an empty string for this case, so we must construct the diff header manually.
        diff_string = f"--- /dev/null\n+++ b/{actual_file_path}\n"
    else:
        from_file, to_file = _get_diff_paths(
            actual_file_path,
            content_before_patch if not is_new_file else None,
            new_content_full,
        )
        diff_lines = _generate_diff_with_no_newline_handling(
            from_file=from_file,
            to_file=to_file,
            from_content=content_before_patch,
            to_content=new_content_full,
        )

        diff_string = "".join(diff_lines)

    return ProcessedPatchResult(
        new_content=new_content_full,
        diff_block=ProcessedDiffBlock(llm_file_path=parsed_block.llm_file_path, unified_diff=diff_string),
    )


def process_patches_sequentially(
    original_file_contents: FileContents,
    llm_response: str,
    session_root: Path,
) -> tuple[FileContents, FileContents, list[WarningMessage]]:
    """
    The single, robust parsing engine that drives all diffing operations.

    This function consumes the `process_llm_response_stream` generator to calculate
    the final state of all files after patches have been applied. It does this in
    a single pass for efficiency.

    Args:
        original_file_contents: An immutable mapping of the original file contents.
        llm_response: The raw response from the language model.
        session_root: The root path of the session.

    Returns:
        A tuple containing:
        - The final contents of all files after patches.
        - The baseline "before" contents, updated with any filesystem fallbacks.
        - A list of any warnings that were generated.
    """
    warnings: list[WarningMessage] = []
    final_contents: FileContents = {}
    baseline_contents: FileContents = {}

    stream_processor = process_llm_response_stream(original_file_contents, llm_response, session_root)

    for item in stream_processor:
        match item:
            case WarningMessage():
                warnings.append(item)
            case PatchApplicationResult() as result:
                # This is always the last item, containing the final aggregated state.
                final_contents = result.post_patch_contents
                baseline_contents = result.baseline_contents_for_diff
                break  # No need to process further
            case _:
                pass

    return final_contents, baseline_contents, warnings


def _yield_remaining_text(text: str) -> Iterator[str | UnparsedBlock]:
    """
    Helper to yield remaining text, classifying it as conversational or an incomplete block.
    """
    # Heuristic to detect an incomplete block.
    # If it looks like a SEARCH block but isn't complete, treat it as an UnparsedBlock
    # to prevent broken Markdown rendering.
    if _INCOMPLETE_BLOCK_REGEX.search(text) and ">>>>>>> REPLACE" not in text:
        yield UnparsedBlock(text=text)
    else:
        yield text


def process_llm_response_stream(
    original_file_contents: FileContents,
    llm_response: str,
    session_root: Path,
) -> Iterator[StreamYieldItem | PatchApplicationResult]:
    """
    The single, robust parsing engine that drives all diffing operations.

    This generator uses a "scan-and-yield" approach with `finditer` to preserve
    all text from the LLM response, including interstitial conversational text
    and newlines that would be lost by a `split()`-based approach. It encapsulates
    its own state, creating a temporary copy of file contents to ensure that each
    patch for a given file is applied against the result of the previous one.

    It yields items representing the entire parsed sequence: conversational text,
    processed diff blocks, and warnings. Finally, it yields a PatchApplicationResult
    with the final state.

    Args:
        original_file_contents: An immutable mapping of the original file contents.
        llm_response: The raw response from the language model.
        session_root: The root path of the session.

    Yields:
        Either a string (for conversational text), a ProcessedDiffBlock, or a WarningMessage.
    """
    current_file_contents = dict(original_file_contents)
    original_contents_for_diffing = dict(original_file_contents)
    last_end = 0

    for file_header_match in _FILE_HEADER_REGEX.finditer(llm_response):
        # Yield any conversational text that appeared before this file block
        if file_header_match.start() > last_end:
            yield llm_response[last_end : file_header_match.start()]

        header_line = file_header_match.group(1)
        llm_file_path = header_line.strip().removeprefix("File:").strip()

        # The content for this file block is from the end of its header to the start of the next one
        # or to the end of the string.
        block_content_start = file_header_match.end()
        next_match_start = len(llm_response)
        # Peek ahead to find the start of the next file block
        next_header_iter = _FILE_HEADER_REGEX.finditer(llm_response, pos=block_content_start)
        if next_match := next(next_header_iter, None):
            next_match_start = next_match.start()

        block_content = llm_response[block_content_start:next_match_start]
        block_last_end = 0
        matches = list(_FILE_BLOCK_REGEX.finditer(block_content))

        if not matches:
            # If no SEARCH/REPLACE blocks found, check if it's an incomplete block
            if _INCOMPLETE_BLOCK_REGEX.search(block_content):
                yield FileHeader(llm_file_path=llm_file_path)
                yield UnparsedBlock(text=block_content)
            else:
                # Treat the whole block as conversational
                yield header_line + block_content
        else:
            yield FileHeader(llm_file_path=llm_file_path)
            for match in matches:
                # Yield conversational text inside a file block (between patches)
                if match.start() > block_last_end:
                    yield block_content[block_last_end : match.start()]
                block_last_end = match.end()

                parsed_block = _create_aipatch_from_match(match, llm_file_path)
                resolution = _resolve_file_path(parsed_block, current_file_contents, session_root)

                if resolution.warning:
                    yield WarningMessage(text=resolution.warning)

                if resolution.path is None:
                    yield WarningMessage(text=_create_file_not_found_error(parsed_block.llm_file_path))
                    yield UnparsedBlock(text=match.group("block"))
                    continue

                actual_file_path = resolution.path
                if resolution.fallback_content is not None:
                    current_file_contents[actual_file_path] = resolution.fallback_content
                    original_contents_for_diffing[actual_file_path] = resolution.fallback_content

                is_new_file = actual_file_path not in original_contents_for_diffing
                content_before_patch = current_file_contents.get(actual_file_path, "")
                result = _process_single_diff_block(parsed_block, content_before_patch, is_new_file, actual_file_path)

                if result:
                    if result.new_content or actual_file_path not in current_file_contents:
                        current_file_contents[actual_file_path] = result.new_content
                    else:  # Handles deletion
                        del current_file_contents[actual_file_path]
                    yield result.diff_block
                else:
                    error_text = _create_patch_failed_error(actual_file_path)
                    yield WarningMessage(text=error_text)
                    yield UnparsedBlock(text=match.group("block"))

            if block_last_end < len(block_content):
                remaining_in_block = block_content[block_last_end:]
                yield from _yield_remaining_text(remaining_in_block)

        last_end = file_header_match.end() + len(block_content)

    # Yield any final conversational text after the last file block
    if last_end < len(llm_response):
        remaining_text = llm_response[last_end:]
        yield from _yield_remaining_text(remaining_text)

    # At the very end of the stream, yield the final state for the sequential processor.
    yield PatchApplicationResult(
        post_patch_contents=current_file_contents,
        baseline_contents_for_diff=original_contents_for_diffing,
        warnings=[],  # Warnings are yielded inline during processing, so this is empty.
    )


def generate_unified_diff(original_file_contents: FileContents, llm_response: str, session_root: Path) -> str:
    """
    Generates a single, clean, compound unified diff string of all successful changes.
    This function creates a "best-effort" diff that can be piped to other tools.
    It ignores any failed patches, as warnings about those are handled separately
    by the calling display logic.
    """
    post_patch_contents, baseline_contents, _ = process_patches_sequentially(
        original_file_contents, llm_response, session_root
    )
    all_diffs: list[str] = []

    # Using keys from both dicts ensures we handle file creations and deletions.
    all_files = sorted(list(set(baseline_contents.keys()) | set(post_patch_contents.keys())))

    for file_path in all_files:
        from_content = baseline_contents.get(file_path)
        to_content = post_patch_contents.get(file_path)

        if from_content == to_content:
            continue

        if from_content is None and to_content == "":
            all_diffs.append(f"--- /dev/null\n+++ b/{file_path}\n")
            continue

        from_file, to_file = _get_diff_paths(file_path, from_content, to_content)
        diff_lines = _generate_diff_with_no_newline_handling(
            from_file=from_file,
            to_file=to_file,
            from_content=from_content,
            to_content=to_content,
        )
        all_diffs.extend(diff_lines)

    return "".join(all_diffs)


def generate_display_items(
    original_file_contents: FileContents, llm_response: str, session_root: Path
) -> list[DisplayItem]:
    """
    Generates a list of structured display items for rendering.
    """
    items: list[DisplayItem] = []
    stream = process_llm_response_stream(original_file_contents, llm_response, session_root)

    for item in stream:
        match item:
            case str() as text:
                if text:
                    items.append({"type": "markdown", "content": text})
            case FileHeader(llm_file_path=llm_file_path):
                items.append({"type": "markdown", "content": f"File: `{llm_file_path}`\n"})
            case ProcessedDiffBlock(unified_diff=diff_string):
                items.append({"type": "diff", "content": diff_string})
            case WarningMessage(text=warning_text):
                items.append({"type": "text", "content": f"⚠️ {warning_text}\n"})
            case UnparsedBlock(text=unparsed_text):
                items.append({"type": "text", "content": unparsed_text})
            case PatchApplicationResult():
                pass  # Ignore final state object in display

    return items


def recompute_derived_content(
    assistant_content: str, context_files: list[str], session_root: Path
) -> DerivedContent | None:
    """
    Recomputes the derived content (diffs, display items) for an assistant message.

    This function takes the raw content from an assistant, compares it against the
    current state of files on disk, and generates a new `DerivedContent` object.
    It returns None if no meaningful derived content (like a diff) can be produced.
    """
    original_file_contents = build_original_file_contents(context_files, session_root)

    unified_diff = generate_unified_diff(original_file_contents, assistant_content, session_root)
    display_items = generate_display_items(original_file_contents, assistant_content, session_root)

    # Logic from prompt.py: only create derived content if there's a diff or if
    # the display items are more than just the raw content (e.g., have warnings).
    if unified_diff or (display_items and "".join(item["content"] for item in display_items) != assistant_content):
        return DerivedContent(unified_diff=unified_diff, display_content=display_items)

    return None
