import difflib
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class DiffBlock:
    """Represents a single SEARCH/REPLACE block for a file."""

    file_path: str
    search_block: str
    replace_block: str


def _parse_single_block(block_text: str) -> DiffBlock:
    """Parses the raw text of a single 'File:' block into a DiffBlock."""
    if not block_text.strip():
        raise ValueError("Cannot parse an empty block.")

    lines = block_text.strip().splitlines()
    file_path = lines[0].strip()
    body_lines = lines[1:]

    try:
        search_start_index = body_lines.index("<<<<<<< SEARCH")
        divider_index = body_lines.index("=======")
        replace_end_index = body_lines.index(">>>>>>> REPLACE")
    except ValueError as e:
        raise ValueError(
            "Could not parse SEARCH/REPLACE markers. The block might be malformed."
        ) from e

    search_block = "\n".join(body_lines[search_start_index + 1 : divider_index])
    replace_block = "\n".join(body_lines[divider_index + 1 : replace_end_index])

    return DiffBlock(
        file_path=file_path,
        search_block=search_block,
        replace_block=replace_block,
    )


def _generate_diff_for_block(
    diff_block: DiffBlock, original_file_contents: dict[str, str]
) -> str:
    """Generates a unified diff string for a single DiffBlock."""
    original_content = original_file_contents.get(diff_block.file_path, "")

    # Handle Deletion
    if not diff_block.replace_block.strip():
        if diff_block.file_path not in original_file_contents:
            raise ValueError(
                f"Cannot delete a file that is not in context: {diff_block.file_path}"
            )

        if diff_block.search_block.strip() != original_content.strip():
            raise ValueError(
                f"To delete '{diff_block.file_path}', the SEARCH block must match the entire file content."
            )
        new_content = ""

    # Handle Creation
    elif not diff_block.search_block.strip():
        if diff_block.file_path in original_file_contents:
            raise ValueError(
                f"File '{diff_block.file_path}' already exists; cannot create it."
            )
        new_content = diff_block.replace_block

    # Handle Modification
    else:
        if diff_block.file_path not in original_file_contents:
            raise ValueError(
                f"Cannot modify a file that is not in context: {diff_block.file_path}"
            )

        if diff_block.search_block not in original_content:
            search_diff = "".join(
                difflib.unified_diff(
                    diff_block.search_block.splitlines(keepends=True),
                    original_content.splitlines(keepends=True),
                    fromfile="llm_search_block",
                    tofile="original_file_content",
                )
            )
            raise ValueError(
                f"The SEARCH block was not found in '{diff_block.file_path}'.\n"
                f"--- Diff of SEARCH block vs Original File ---\n{search_diff}"
            )
        new_content = original_content.replace(
            diff_block.search_block, diff_block.replace_block, 1
        )

    diff: Iterable[str] = difflib.unified_diff(
        original_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{diff_block.file_path}",
        tofile=f"b/{diff_block.file_path}",
    )
    return "".join(diff)


def generate_diff_from_response(
    original_file_contents: dict[str, str], llm_response: str
) -> str:
    """
    Parses the LLM's full response, processes each block, and returns a
    single unified diff.
    """
    final_diff_parts = []
    response_blocks = llm_response.strip().split("File: ")

    if not response_blocks or not any(b.strip() for b in response_blocks):
        return "Error: LLM response did not contain any valid 'File:' blocks."

    for block_text in response_blocks:
        if not block_text.strip():
            continue

        try:
            diff_block = _parse_single_block(block_text)
            diff_part = _generate_diff_for_block(diff_block, original_file_contents)
            final_diff_parts.append(diff_part)
        except ValueError as e:
            file_path = block_text.strip().splitlines()[0]
            return f"Error processing block for '{file_path}': {e}"

    return "".join(final_diff_parts)
