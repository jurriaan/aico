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


def create_patched_content(original_content: str, search_block: str, replace_block: str) -> str | None:
    # Stage 1: Exact match
    exact_patch = _try_exact_string_patch(original_content, search_block, replace_block)
    if exact_patch is not None:
        return exact_patch

    # Stage 2: Whitespace-insensitive match
    flexible_patch = _try_whitespace_flexible_patch(original_content, search_block, replace_block)
    if flexible_patch is not None:
        return flexible_patch

    return None
