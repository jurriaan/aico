from collections.abc import Iterator
from pathlib import Path

import regex as re

from aico.diffing.diff_utils import generate_diff_with_no_newline_handling
from aico.diffing.patching import create_patched_content
from aico.fs import get_context_file_contents as build_original_file_contents
from aico.models import (
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
    try:
        # Resolve the full path to handle '..' and symlinks
        full_disk_path = (session_root / patch.llm_file_path).resolve()

        # Ensure the resolved path is actually inside session_root
        # This raises ValueError if full_disk_path is outside session_root
        _ = full_disk_path.relative_to(session_root.resolve())

        if full_disk_path.is_file():
            content = full_disk_path.read_text(encoding="utf-8")
            warning = (
                f"File '{patch.llm_file_path}' was not in the session context but was found on disk. "
                "Consider adding it to the session."
            )
            return ResolvedFilePath(path=patch.llm_file_path, warning=warning, fallback_content=content)

    except (ValueError, OSError):
        # ValueError: Path traversal detected (file is outside root)
        # OSError: File read error or path construction error
        pass

    # 4. Failure
    return ResolvedFilePath(path=None, warning=None, fallback_content=None)


def _create_aipatch_from_match(match: re.Match[str], llm_file_path: str) -> AIPatch:  # ty: ignore[invalid-type-form]
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
    new_content_full = create_patched_content(
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
        diff_lines = generate_diff_with_no_newline_handling(
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
    current_file_contents: dict[str, str] = dict(original_file_contents)
    original_contents_for_diffing: dict[str, str] = dict(original_file_contents)
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


def _build_unified_diff(baseline_contents: FileContents, final_contents: FileContents) -> str:
    """
    Generates a single, clean, compound unified diff string of all successful changes.
    This is a pure function that takes baseline and final file contents and returns a diff.
    """
    all_diffs: list[str] = []

    # Using keys from both dicts ensures we handle file creations and deletions.
    all_files = sorted(list(set(baseline_contents.keys()) | set(final_contents.keys())))

    for file_path in all_files:
        from_content = baseline_contents.get(file_path)
        to_content = final_contents.get(file_path)

        if from_content == to_content:
            continue

        if from_content is None and to_content == "":
            all_diffs.append(f"--- /dev/null\n+++ b/{file_path}\n")
            continue

        from_file, to_file = _get_diff_paths(file_path, from_content, to_content)
        diff_lines = generate_diff_with_no_newline_handling(
            from_file=from_file,
            to_file=to_file,
            from_content=from_content,
            to_content=to_content,
        )
        all_diffs.extend(diff_lines)

    return "".join(all_diffs)


def analyze_response(
    original_file_contents: FileContents,
    llm_response: str,
    session_root: Path,
) -> tuple[str, list[DisplayItem], list[str]]:
    """
    Analyzes the LLM response in a single pass, returning all derived outputs.

    It processes the stream once and returns:
    - The unified diff string
    - The structured display items
    - A list of warning messages
    """
    display_items: list[DisplayItem] = []
    warnings: list[str] = []
    unified_diff: str = ""
    baseline_contents: FileContents = {}
    final_contents: FileContents = {}

    stream = process_llm_response_stream(original_file_contents, llm_response, session_root)

    for item in stream:
        match item:
            case str() as text:
                if text:
                    display_items.append({"type": "markdown", "content": text})
            case FileHeader(llm_file_path=llm_file_path):
                display_items.append({"type": "markdown", "content": f"File: `{llm_file_path}`\n"})
            case ProcessedDiffBlock(unified_diff=diff_string):
                display_items.append({"type": "diff", "content": diff_string})
            case WarningMessage(text=warning_text):
                display_items.append({"type": "text", "content": f"⚠️ {warning_text}\n"})
                warnings.append(warning_text)
            case UnparsedBlock(text=unparsed_text):
                display_items.append({"type": "text", "content": unparsed_text})
            case PatchApplicationResult() as result:
                baseline_contents = result.baseline_contents_for_diff
                final_contents = result.post_patch_contents

    unified_diff = _build_unified_diff(baseline_contents, final_contents)

    return unified_diff, display_items, warnings


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

    unified_diff, display_items, _ = analyze_response(original_file_contents, assistant_content, session_root)

    # Logic from prompt.py: only create derived content if there's a diff or if
    # the display items are more than just the raw content (e.g., have warnings).
    if unified_diff or (display_items and "".join(item["content"] for item in display_items) != assistant_content):
        return DerivedContent(unified_diff=unified_diff, display_content=display_items)

    return None
