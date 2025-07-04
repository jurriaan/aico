# pyright: standard

from collections.abc import Callable
from pathlib import Path

import pytest

from aico.diffing import (
    _apply_patches,
    generate_display_content,
    generate_unified_diff,
    process_llm_response_stream,
)


def test_apply_patches_single_change(tmp_path: Path) -> None:
    # GIVEN original content and a valid patch
    original_contents = {"file.py": "old content"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE"

    # WHEN _apply_patches is called
    final_contents, _, warnings = _apply_patches(original_contents, llm_response, tmp_path)

    # THEN the final content is correct and there are no warnings
    assert final_contents == {"file.py": "new content\n"}
    assert not warnings


def test_apply_patches_sequential_changes(tmp_path: Path) -> None:
    # GIVEN original content and two sequential patches for the same file
    original_contents = {"file.py": "line 1\nline 2"}
    llm_response = (
        "File: file.py\n<<<<<<< SEARCH\nline 1\n=======\nline one\n>>>>>>> REPLACE\n"
        "Some chat.\n"
        "File: file.py\n<<<<<<< SEARCH\nline 2\n=======\nline two\n>>>>>>> REPLACE"
    )

    # WHEN _apply_patches is called
    final_contents, _, warnings = _apply_patches(original_contents, llm_response, tmp_path)

    # THEN the final content has both patches applied in order
    # The `replace_content` from the regex captures the trailing newline.
    assert final_contents == {"file.py": "line one\nline two\n"}
    assert not warnings


def test_apply_patches_failed_patch_is_ignored(tmp_path: Path) -> None:
    # GIVEN original content and a patch that will fail
    original_contents = {"file.py": "original content"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nnon-existent\n=======\nnew\n>>>>>>> REPLACE"

    # WHEN _apply_patches is called
    final_contents, _, warnings = _apply_patches(original_contents, llm_response, tmp_path)

    # THEN the final content is unchanged
    assert final_contents == original_contents
    assert not warnings


def test_apply_patches_filesystem_fallback(tmp_path: Path) -> None:
    # GIVEN an empty context, but a file on disk
    (tmp_path / "file.py").write_text("disk content")
    original_contents = {}
    llm_response = "File: file.py\n<<<<<<< SEARCH\ndisk content\n=======\nnew content\n>>>>>>> REPLACE"

    # WHEN _apply_patches is called
    final_contents, _, warnings = _apply_patches(original_contents, llm_response, tmp_path)

    # THEN the final content is correct and a warning is returned
    assert final_contents == {"file.py": "new content\n"}
    assert len(warnings) == 1
    assert "was not in the session context but was found on disk" in warnings[0].text


def test_process_llm_response_stream_handles_fallback(tmp_path: Path) -> None:
    # GIVEN a file on disk but not in context
    (tmp_path / "file.py").write_text("disk content")
    original_contents = {}
    llm_response = "File: file.py\n<<<<<<< SEARCH\ndisk content\n=======\nnew content\n>>>>>>> REPLACE"

    # WHEN the stream is processed
    stream_results = list(process_llm_response_stream(original_contents, llm_response, tmp_path))

    # THEN a warning and a valid diff block are yielded
    assert len(stream_results) == 2
    assert "WarningMessage" in str(stream_results[0])
    assert "ProcessedDiffBlock" in str(stream_results[1])
    # And the diff is correct, showing a modification not a creation
    assert "--- a/file.py" in stream_results[1].unified_diff


def test_generate_diff_for_standard_change(tmp_path: Path) -> None:
    # GIVEN original content and a well-formed LLM response
    original_contents = {"file.py": "old_line = 1"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nold_line = 1\n=======\nnew_line = 2\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN it is a valid unified diff
    assert "--- a/file.py" in diff
    assert "+++ b/file.py" in diff
    assert "-old_line = 1" in diff
    assert "+new_line = 2" in diff


def test_generate_diff_for_new_file_creation(tmp_path: Path) -> None:
    # GIVEN no original content and an LLM response to create a file
    original_contents = {}
    llm_response = "File: new_file.py\n<<<<<<< SEARCH\n=======\nprint('hello world')\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN it shows the file being created from /dev/null
    assert "--- /dev/null" in diff
    assert "+++ b/new_file.py" in diff
    assert "+print('hello world')" in diff


def test_generate_diff_for_file_deletion(tmp_path: Path) -> None:
    # GIVEN original content and an LLM response to delete the file
    file_content = "line 1\nline 2"
    original_contents = {"file.py": file_content}
    llm_response = f"File: file.py\n<<<<<<< SEARCH\n{file_content}\n=======\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN it shows the file being deleted to /dev/null
    assert "--- a/file.py" in diff
    assert "+++ /dev/null" in diff
    assert "-line 1" in diff
    assert "-line 2" in diff


@pytest.mark.parametrize(
    "indentation",
    ["\t ", "  \t ", "\t", " \t  ", "  "],
    ids=["tab_space", "space_tab_space", "tab", "tab_space", "space"],
)
def test_whitespace_flexible_patching_succeeds(indentation, tmp_path: Path) -> None:
    # GIVEN original content with 4-space indent and a SEARCH block with different indent
    original_contents = {"file.py": "def my_func():\n    print('hello')\n"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "def my_func():\n"
        f"{indentation}print('hello')\n"
        "=======\n"
        "def my_func():\n"
        "    # A new comment\n"
        "    print('world')\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the patch is applied correctly with original indentation
    assert "-    print('hello')" in diff
    assert "+    # A new comment" in diff
    assert "+    print('world')" in diff


def test_patch_failure_when_search_block_not_found(tmp_path: Path) -> None:
    # GIVEN a SEARCH block that doesn't exist in the original content
    original_contents = {"file.py": "original content"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nnon-existent content\n=======\nnew content\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN a failed patch diff is returned with an error
    assert "a/file.py" in diff
    assert "b/file.py (patch failed)" in diff
    assert "Error: The SEARCH block from the AI could not be found" in diff
    assert "--- SEARCH BLOCK ---" in diff
    assert "non-existent content" in diff
    assert "--- END SEARCH BLOCK ---" in diff


def test_error_when_file_not_found_in_context_or_on_disk(tmp_path: Path) -> None:
    # GIVEN an LLM response for a file not in the context or on disk
    original_contents = {"real_file.py": "content"}
    llm_response = "File: unknown_file.py\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN a 'not found' diff is generated
    assert "a/unknown_file.py (not found)" in diff
    assert "b/unknown_file.py (not found)" in diff
    assert "Error: The file path 'unknown_file.py' from the AI does not match any file in the context." in diff


def test_handling_of_malformed_llm_responses(tmp_path: Path) -> None:
    # GIVEN a malformed LLM response
    malformed_response = "File: file.py\nSome malformed content without blocks."
    # WHEN the diff is generated
    diff = generate_unified_diff({}, malformed_response, tmp_path)

    # THEN an empty diff is produced, as there are no valid blocks to parse
    assert diff == ""


def test_multi_block_llm_response_with_conversation(tmp_path: Path) -> None:
    # GIVEN original contents for two files and a multi-block response with conversation
    original_contents = {
        "file_one.py": "one",
        "file_two.py": "two",
    }
    llm_response = (
        "Here is the first change:\n"
        "File: file_one.py\n"
        "<<<<<<< SEARCH\n"
        "one\n"
        "=======\n"
        "1\n"
        ">>>>>>> REPLACE\n"
        "\nAnd here is the second change for the other file:\n"
        "File: file_two.py\n"
        "<<<<<<< SEARCH\n"
        "two\n"
        "=======\n"
        "2\n"
        ">>>>>>> REPLACE\n"
        "All done!"
    )

    # WHEN the unified diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the output contains two complete, valid diffs and no conversation
    assert "Here is the first change" not in diff
    assert "All done!" not in diff
    assert "--- a/file_one.py" in diff
    assert "+++ b/file_one.py" in diff
    assert "-one" in diff
    assert "+1" in diff
    assert "--- a/file_two.py" in diff
    assert "+++ b/file_two.py" in diff
    assert "-two" in diff
    assert "+2" in diff

    # WHEN the display content is generated
    display_content = generate_display_content(original_contents, llm_response, tmp_path)

    # THEN the output contains the conversation and markdown diffs
    assert "Here is the first change" in display_content
    assert "And here is the second change" in display_content
    assert "All done!" in display_content
    assert "```diff\n--- a/file_one.py" in display_content
    assert "```diff\n--- a/file_two.py" in display_content


def test_ambiguous_patch_succeeds_on_first_match(tmp_path: Path) -> None:
    # GIVEN a file where the target code block appears twice
    original_contents = {"file.py": "repeatable_line = 1\n\nsome_other_code = True\n\nrepeatable_line = 1\n"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nrepeatable_line = 1\n=======\nchanged_line = 2\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the patch is applied only to the first occurrence
    assert "patch failed" not in diff
    assert "ambiguous" not in diff
    diff_lines = diff.splitlines()

    # The first block should be changed
    assert "-repeatable_line = 1" in diff_lines
    assert "+changed_line = 2" in diff_lines

    # Verify context lines are present to ensure we're looking at the right part of the diff
    assert " some_other_code = True" in diff_lines

    # Count occurrences to ensure the change happened only once
    assert diff.count("-repeatable_line = 1") == 1
    assert diff.count("+changed_line = 2") == 1


def test_patching_with_blank_lines_in_search_block(tmp_path: Path) -> None:
    # GIVEN a search block containing blank lines
    original_contents = {"file.py": "line one\n\nline three"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nline one\n\nline three\n=======\nreplacement\n>>>>>>> REPLACE"
    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the patch applies successfully
    assert "patch failed" not in diff
    assert "-line one" in diff
    assert "+replacement" in diff


def test_patching_with_trailing_blank_lines_in_search_block(tmp_path: Path) -> None:
    # GIVEN original content and a search block with trailing blank lines
    # This specifically tests that the diffing regex doesn't prematurely consume
    # the trailing newlines as part of the delimiter's whitespace.
    original_contents = {"file.py": "code block\n\n\nsome other code"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\ncode block\n\n\n=======\nreplacement\n>>>>>>> REPLACE"
    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the patch applies successfully, proving the SEARCH block was parsed correctly
    assert "patch failed" not in diff
    assert "-code block" in diff
    assert "+replacement" in diff
    assert "some other code" in diff  # check context is preserved


def test_patch_that_changes_indentation(tmp_path: Path) -> None:
    # GIVEN code that needs to be indented
    original_contents = {"file.py": "to_be_indented()"}
    llm_response = (
        "File: file.py\n<<<<<<< SEARCH\nto_be_indented()\n=======\nif True:\n    to_be_indented()\n>>>>>>> REPLACE"
    )
    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the diff is generated correctly
    assert "patch failed" not in diff
    assert "+    to_be_indented()" in diff


def test_patch_that_outdents_code(tmp_path: Path) -> None:
    # GIVEN a file with code inside an if block
    original_contents = {"file.py": "if True:\n    code_to_outdent()\n"}
    llm_response = (
        "File: file.py\n<<<<<<< SEARCH\nif True:\n    code_to_outdent()\n=======\ncode_to_outdent()\n>>>>>>> REPLACE"
    )
    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the patch applies correctly, with the code now outdented
    assert "patch failed" not in diff
    assert "-if True:" in diff
    assert "-    code_to_outdent()" in diff
    assert "+code_to_outdent()" in diff


def test_patch_for_multi_line_indent(tmp_path: Path) -> None:
    # GIVEN a file with a multi-line block
    original_contents = {"file.py": "print('one')\nprint('two')\n"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "print('one')\n"
        "print('two')\n"
        "=======\n"
        "try:\n"
        "    print('one')\n"
        "    print('two')\n"
        "except Exception:\n"
        "    pass\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated to wrap the block
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the entire block is correctly indented
    assert "patch failed" not in diff
    assert "+try:" in diff
    assert "+    print('one')" in diff
    assert "+    print('two')" in diff
    assert "+except Exception:" in diff
    assert "+    pass" in diff
    assert "-print('one')" in diff
    assert "-print('two')" in diff


# --- Hardening Tests from Plan ---


def test_predictability_no_fuzzy_matching_on_paths(tmp_path: Path) -> None:
    # GIVEN a context containing one file
    original_contents = {"src/models/ai.py": "class AI: pass"}

    # AND an LLM response that targets a different but similarly named file
    # that is NOT in context and NOT on disk.
    llm_response = (
        "File: src/models/dto/ai.py\n"
        "<<<<<<< SEARCH\nclass DTO_AI: pass\n=======\nclass DTO_AI_MODIFIED: pass\n>>>>>>> REPLACE\n"
    )

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN it fails with a "file not found" error for the correct path
    assert "a/src/models/dto/ai.py (not found)" in diff

    # AND it does NOT create a diff for the similarly named file that was in context
    assert "--- a/src/models/ai.py" not in diff


def test_partial_deletion_inside_file(tmp_path: Path) -> None:
    # GIVEN a file with a function and an AI patch to remove lines from it
    original_contents = {"file.py": "def my_func():\n    line_one = 1\n    line_two = 2\n    line_three = 3\n"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\n    line_one = 1\n    line_two = 2\n=======\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the diff removes only those lines, leaving the surrounding context
    assert "patch failed" not in diff
    assert "def my_func()" in diff
    assert "-    line_one = 1" in diff
    assert "-    line_two = 2" in diff
    assert "    line_three = 3" in diff
    assert "+    " not in diff


def test_empty_search_on_existing_file_fails(tmp_path: Path) -> None:
    # GIVEN an existing, non-empty file and an invalid AI patch with an empty search block
    original_contents = {"file.py": "some_content = True"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\n=======\nnew_content = False\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN it fails with a patch failed error because this is invalid for an existing file
    assert "patch failed" in diff
    assert "The SEARCH block from the AI could not be found" in diff


def test_patch_robust_to_delimiters_in_content(tmp_path: Path) -> None:
    # GIVEN a file containing a diff delimiter and an AI patch that also contains it
    original_contents = {"file.py": "line_one = 1\n<<<<<<< SEARCH\nline_three = 3\n"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "line_one = 1\n"
        "<<<<<<< SEARCH\n"
        "line_three = 3\n"
        "=======\n"
        "content was changed\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the patch is applied successfully, proving the parser's robustness
    assert "patch failed" not in diff
    assert "+content was changed" in diff
    assert "-<<<<<<< SEARCH" in diff


def test_patch_with_inconsistent_trailing_newlines(tmp_path: Path) -> None:
    # GIVEN a source file with a trailing newline and an AI SEARCH block without one
    original_contents = {"file.py": "line1\nline2\n"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nline1\nline2\n=======\nline1\nline_two_changed\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the patch applies successfully due to flexible matching
    assert "patch failed" not in diff
    assert "-line2" in diff
    assert "+line_two_changed" in diff


def test_whitespace_only_change(tmp_path: Path) -> None:
    # GIVEN a file with code separated by one blank line and a patch to add another
    original_contents = {"file.py": "line_one\n\nline_three\n"}
    llm_response = (
        "File: file.py\n<<<<<<< SEARCH\nline_one\n\nline_three\n=======\nline_one\n\n\nline_three\n>>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the diff correctly shows the addition of one blank line
    assert "patch failed" not in diff
    diff_lines = diff.splitlines()
    added_lines = [line for line in diff_lines if line.startswith("+") and "+++" not in line]
    # The change from the original content to the new content is one added blank line.
    assert len(added_lines) == 1
    assert added_lines[0] == "+"


def test_whitespace_only_change_missing_newline_in_original(tmp_path: Path) -> None:
    # GIVEN a file with code separated by one blank line and a patch to add another
    original_contents = {"file.py": "line_one\n\nline_three"}
    llm_response = (
        "File: file.py\n<<<<<<< SEARCH\nline_one\n\nline_three\n=======\nline_one\n\n\nline_three\n>>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the diff correctly shows the addition of one blank line and the fixing of the missing newline
    assert diff == (
        "--- a/file.py\n"
        + "+++ b/file.py\n"
        + "@@ -1,3 +1,4 @@\n"
        + " line_one\n"
        + " \n"
        + "-line_three\n"
        + "\\ No newline at end of file\n"
        + "+\n"
        + "+line_three\n"
    )


def test_mismatched_line_endings_patch_succeeds(tmp_path: Path) -> None:
    # GIVEN a source file with CRLF endings and an AI patch with LF endings
    original_contents = {"file.py": "line1\r\nline2\r\n"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nline1\nline2\n=======\nnew_line1\nnew_line2\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the patch applies successfully because line endings are normalized for comparison
    assert "patch failed" not in diff
    assert "-line1" in diff
    assert "-line2" in diff
    assert "+new_line1" in diff
    assert "+new_line2" in diff


# --- Tests for Dual-Format Diff Presentation ---


def test_generate_pipeable_diff_with_conversation(tmp_path: Path) -> None:
    # GIVEN an LLM response with conversational text and a diff block
    original_contents = {"file.py": "old_line"}
    llm_response = (
        "Hello! I've made the change you requested.\n\n"
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "old_line\n"
        "=======\n"
        "new_line\n"
        ">>>>>>> REPLACE\n\n"
        "Let me know if you need anything else!"
    )

    # WHEN the pipeable diff is generated
    pipeable_diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the output is a clean diff with no conversational text
    assert "Hello!" not in pipeable_diff
    assert "Let me know" not in pipeable_diff
    assert "--- a/file.py" in pipeable_diff
    assert "+++ b/file.py" in pipeable_diff
    assert "-old_line" in pipeable_diff
    assert "+new_line" in pipeable_diff


def test_generate_pipeable_diff_from_conversation_only_returns_empty(tmp_path: Path) -> None:
    # GIVEN an LLM response with only conversational text
    original_contents = {"file.py": "old_line"}
    llm_response = "I'm not sure how to make that change. Could you clarify?"

    # WHEN the pipeable diff is generated
    pipeable_diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the output is an empty string
    assert pipeable_diff == ""


def test_generate_embedded_markdown_diff_with_conversation(tmp_path: Path) -> None:
    # GIVEN an LLM response with conversational text and a diff block
    original_contents = {"file.py": "old_line"}
    llm_response = (
        "Hello! I've made the change you requested.\n\n"
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "old_line\n"
        "=======\n"
        "new_line\n"
        ">>>>>>> REPLACE\n\n"
        "Let me know if you need anything else!"
    )

    # WHEN the embedded markdown diff is generated
    markdown_output = generate_display_content(original_contents, llm_response, tmp_path)

    # THEN the conversational text is preserved
    assert "Hello! I've made the change you requested." in markdown_output
    assert "Let me know if you need anything else!" in markdown_output

    # AND the SEARCH/REPLACE block is replaced with a Markdown diff block
    assert "<<<<<<< SEARCH" not in markdown_output
    assert "```diff" in markdown_output
    assert "--- a/file.py" in markdown_output
    assert "-old_line" in markdown_output
    assert "+new_line" in markdown_output
    assert "```" in markdown_output


def test_generate_embedded_markdown_diff_from_conversation_only_is_unchanged(tmp_path: Path) -> None:
    # GIVEN an LLM response with only conversational text
    original_contents = {"file.py": "old_line"}
    llm_response = "I'm not sure how to make that change. Could you clarify?"

    # WHEN the embedded markdown diff is generated
    markdown_output = generate_display_content(original_contents, llm_response, tmp_path)

    # THEN the output is the original response, unchanged
    assert markdown_output == llm_response


def test_generate_embedded_markdown_diff_malformed_block(tmp_path: Path) -> None:
    # GIVEN an LLM response with conversational text and a malformed block
    original_contents = {}
    llm_response = (
        "I tried to make a change, but I might have messed up the format.\n\n"
        "File: file.py\n"
        "This is not a valid diff block because it's missing the delimiters.\n"
    )

    # WHEN the embedded markdown diff is generated using the new robust parser
    markdown_output = generate_display_content(original_contents, llm_response, tmp_path)

    # THEN the malformed block is treated as conversational text and is preserved as-is.
    # The entire original response should be returned untouched.
    assert markdown_output == llm_response


@pytest.mark.parametrize(
    "llm_response_template",
    [
        (
            "   File: file.py\n"
            "   <<<<<<< SEARCH\n"  # Indented
            "   {search}\n"
            "   =======\n"
            "   {replace}\n"
            "   >>>>>>> REPLACE"
        ),
        (
            "File: file.py\n"
            "   <<<<<<< SEARCH\n"  # Indented
            "{search}\n"
            "   =======\n"
            "{replace}\n"
            "   >>>>>>> REPLACE   "  # Trailing whitespace
        ),
        (
            "File: file.py\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"  # No trailing newli
        ),
    ],
    ids=["fully_indented", "indented", "no_trailing_newline"],
)
@pytest.mark.parametrize(
    "func_to_test",
    [generate_unified_diff, generate_display_content],
    ids=["unified_diff", "display_content"],
)
def test_parser_is_robust_to_formatting(
    llm_response_template: str, func_to_test: Callable[[dict[str, str], str, Path], str], tmp_path: Path
) -> None:
    # GIVEN an LLM response with quirky but valid formatting
    search_block = "old_line"
    replace_block = "new_line"
    llm_response = llm_response_template.format(search=search_block, replace=replace_block)
    original_contents = {"file.py": "old_line"}

    # WHEN the diff/content is generated
    result = func_to_test(original_contents, llm_response, tmp_path)

    # THEN the content is generated successfully without a malformed block error
    assert "MALFORMED_BLOCK" not in result
    assert "+new_line" in result
    assert "-old_line" in result


@pytest.mark.parametrize(
    "whitespace_search_block",
    ["\n", "  \n  ", "\t", " \n \t \n "],
    ids=["newline", "spaces_and_newline", "tab", "mixed_whitespace"],
)
def test_whitespace_only_search_block_fails_cleanly(
    whitespace_search_block: str,
    tmp_path: Path,
) -> None:
    """
    Tests that a SEARCH block containing only whitespace doesn't cause an
    AMBIGUOUS_PATCH error on a file with multiple blank lines. It should
    instead fail as a standard non-match.
    """
    # GIVEN a file with multiple blank lines
    original_contents = {"file.py": "line_one\n\n\nline_two"}
    # AND an LLM response where the SEARCH block is only whitespace
    llm_response = f"File: file.py\n<<<<<<< SEARCH\n{whitespace_search_block}\n=======\nsome_content\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the diff should report a standard "patch failed" error, not an "ambiguous" one
    # Note: The flexible patcher will fail, and so will the exact patcher, leading to this error.
    assert "ambiguous" not in diff.lower()
    assert "patch failed" in diff
    assert "could not be found" in diff


def test_no_newline_marker_added_for_existing_file_without_trailing_newline(tmp_path: Path) -> None:
    """Verifies the '\\ No newline...' marker is added for an existing file missing a final newline."""
    # GIVEN an existing file without a trailing newline and an LLM patch
    original_contents = {"file.py": "print('old')"}
    llm_response = "File: file.py\n<<<<<<< SEARCH\nprint('old')\n=======\nprint('new')\n>>>>>>> REPLACE"

    # WHEN the unified diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the diff should contain the "No newline" marker for the original file content
    expected_diff = (
        "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-print('old')\n\\ No newline at end of file\n+print('new')\n"
    )
    assert diff == expected_diff


def test_multi_patch_on_single_file(tmp_path: Path) -> None:
    # GIVEN a file and an LLM response with two sequential patches for that file
    original_contents = {"file.py": "line 1\nline 2"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "line 1\n"
        "=======\n"
        "line one changed\n"
        ">>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\n"
        "line 2\n"
        "=======\n"
        "line two changed\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN both patches should be applied sequentially to the same file
    expected_diff = (
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-line 1\n"
        "-line 2\n"
        "\\ No newline at end of file\n"
        "+line one changed\n"
        "+line two changed\n"
    )
    assert diff == expected_diff


def test_multi_patch_with_interstitial_conversation(tmp_path: Path) -> None:
    # GIVEN an LLM response with two patches for the same file, separated by conversation
    original_contents = {"file.py": "line 1\nline 2"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "line 1\n"
        "=======\n"
        "line one changed\n"
        ">>>>>>> REPLACE\n"
        "Okay, and now for the second part.\n"
        "<<<<<<< SEARCH\n"
        "line 2\n"
        "=======\n"
        "line two changed\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the unified diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the diff should be clean and contain both changes, with no conversational text
    expected_diff = (
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-line 1\n"
        "-line 2\n"
        "\\ No newline at end of file\n"
        "+line one changed\n"
        "+line two changed\n"
    )
    assert diff == expected_diff

    # WHEN the display content is generated
    display_content = generate_display_content(original_contents, llm_response, tmp_path)

    # THEN it should contain the conversational text between the rendered diffs
    assert "Okay, and now for the second part." in display_content
    assert "File: `file.py`" in display_content
    assert "```diff" in display_content
    # Check that there are two separate diff blocks rendered
    assert display_content.count("```diff") == 2


def test_complex_multi_file_and_multi_patch_scenario(tmp_path: Path) -> None:
    # GIVEN multiple files and a complex response
    original_contents = {"file1.py": "f1 line1", "file2.py": "f2 line1\nf2 line2"}
    llm_response = (
        "First, a simple change.\n"
        "File: file1.py\n"
        "<<<<<<< SEARCH\n"
        "f1 line1\n"
        "=======\n"
        "f1 line1 changed\n"
        ">>>>>>> REPLACE\n"
        "Now for the more complex file.\n"
        "File: file2.py\n"
        "<<<<<<< SEARCH\n"
        "f2 line1\n"
        "=======\n"
        "f2 line1 changed\n"
        ">>>>>>> REPLACE\n"
        "And the second line in that same file.\n"
        "<<<<<<< SEARCH\n"
        "f2 line2\n"
        "=======\n"
        "f2 line2 changed\n"
        ">>>>>>> REPLACE\n"
        "All done."
    )

    # WHEN unified diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN it contains all three changes correctly
    expected_diff = (
        "--- a/file1.py\n"
        "+++ b/file1.py\n"
        "@@ -1 +1 @@\n"
        "-f1 line1\n"
        "\\ No newline at end of file\n"
        "+f1 line1 changed\n"
        "--- a/file2.py\n"
        "+++ b/file2.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-f2 line1\n"
        "-f2 line2\n"
        "\\ No newline at end of file\n"
        "+f2 line1 changed\n"
        "+f2 line2 changed\n"
    )
    assert diff == expected_diff

    # WHEN display content is generated
    display_content = generate_display_content(original_contents, llm_response, tmp_path)

    # THEN it contains all conversational text and all rendered diffs
    assert "First, a simple change." in display_content
    assert "Now for the more complex file." in display_content
    assert "And the second line in that same file." in display_content
    assert "All done." in display_content

    assert display_content.count("```diff") == 3


def test_generate_diff_with_filesystem_fallback(tmp_path: Path) -> None:
    # GIVEN an empty initial context
    original_contents = {}
    # AND a file that exists on disk but is not in the context
    fallback_file = tmp_path / "fallback.py"
    fallback_file.write_text("original content")
    # AND an LLM response targeting that file
    llm_response = "File: fallback.py\n<<<<<<< SEARCH\noriginal content\n=======\nnew content\n>>>>>>> REPLACE"

    # WHEN the unified diff is generated
    # The session_root is the tmp_path where the fallback file exists
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the diff should show a file modification, not a file creation
    expected_diff = (
        "--- a/fallback.py\n"
        "+++ b/fallback.py\n"
        "@@ -1 +1 @@\n"
        "-original content\n"
        "\\ No newline at end of file\n"
        "+new content\n"
    )
    assert diff == expected_diff


def test_no_newline_marker_logic_is_correct_for_new_file_creation(tmp_path: Path) -> None:
    # GIVEN a patch to create a new file that itself has no trailing newline
    original_contents = {}
    llm_response = "File: new.py\n<<<<<<< SEARCH\n=======\nnew content\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the standard diff is produced. Our logic should not run for the `/dev/null` side.
    # The standard `difflib` will correctly add a marker for the new content, and only that one.
    # A bug would cause a second, incorrect marker to be added.
    expected_diff = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+new content\n"
    assert diff == expected_diff


def test_no_newline_marker_logic_is_correct_for_empty_file_diff(tmp_path: Path) -> None:
    # GIVEN a patch to update an enpty file that itself has no trailing newline
    original_contents = {"new.py": ""}
    llm_response = "File: new.py\n<<<<<<< SEARCH\n=======\nnew content\n>>>>>>> REPLACE"

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN the standard diff is produced.
    expected_diff = "--- a/new.py\n+++ b/new.py\n@@ -0,0 +1 @@\n+new content\n"
    assert diff == expected_diff


def test_generate_diff_for_new_empty_file_followed_by_another_file(tmp_path: Path) -> None:
    # GIVEN no original content and an LLM response to create an empty file, then another file
    original_contents = {}
    llm_response = (
        "File: app/__init__.py\n"
        "<<<<<<< SEARCH\n"
        "=======\n"
        ">>>>>>> REPLACE\n"
        "File: app/renderer.py\n"
        "<<<<<<< SEARCH\n"
        "=======\n"
        "import html\n"
        ">>>>>>> REPLACE\n"
    )

    # WHEN the diff is generated
    diff = generate_unified_diff(original_contents, llm_response, tmp_path)

    # THEN it should contain a valid diff for BOTH files
    expected_diff = (
        "--- /dev/null\n+++ b/app/__init__.py\n--- /dev/null\n+++ b/app/renderer.py\n@@ -0,0 +1 @@\n+import html\n"
    )
    assert diff == expected_diff
