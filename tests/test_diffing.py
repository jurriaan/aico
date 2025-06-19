import pytest

from aico.diffing import generate_diff_from_response


def test_generate_diff_for_standard_change() -> None:
    # GIVEN original content and a well-formed LLM response
    original_contents = {"file.py": "old_line = 1"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "old_line = 1\n"
        "=======\n"
        "new_line = 2\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN it is a valid unified diff
    assert "--- a/file.py" in diff
    assert "+++ b/file.py" in diff
    assert "-old_line = 1" in diff
    assert "+new_line = 2" in diff


def test_generate_diff_for_new_file_creation() -> None:
    # GIVEN no original content and an LLM response to create a file
    original_contents = {}
    llm_response = (
        "File: new_file.py\n"
        "<<<<<<< SEARCH\n"
        "=======\n"
        "print('hello world')\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN it shows the file being created from /dev/null
    assert "--- /dev/null" in diff
    assert "+++ b/new_file.py" in diff
    assert "+print('hello world')" in diff


def test_generate_diff_for_file_deletion() -> None:
    # GIVEN original content and an LLM response to delete the file
    file_content = "line 1\nline 2"
    original_contents = {"file.py": file_content}
    llm_response = (
        "File: file.py\n"
        f"<<<<<<< SEARCH\n"
        f"{file_content}\n"
        f"=======\n"
        f">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN it shows the file being deleted to /dev/null
    assert "--- a/file.py" in diff
    assert "+++ /dev/null" in diff
    assert "-line 1" in diff
    assert "-line 2" in diff


def test_whitespace_flexible_patching_succeeds() -> None:
    # GIVEN original content with 4-space indent and a SEARCH block with 2-space indent
    original_contents = {"file.py": "def my_func():\n    print('hello')\n"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "def my_func():\n"
        "  print('hello')\n"
        "=======\n"
        "def my_func():\n"
        "    # A new comment\n"
        "    print('world')\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the patch is applied correctly with original indentation
    assert "-    print('hello')" in diff
    assert "+    # A new comment" in diff
    assert "+    print('world')" in diff


@pytest.mark.parametrize(
    "llm_filename",
    [
        "src/app/main.py",  # Exact match
        "main.py",  # Basename match
        "src/ap/main.py",  # Fuzzy match
    ],
)
def test_filename_matching_logic(llm_filename: str) -> None:
    # GIVEN original content with a specific path
    original_contents = {"src/app/main.py": "import os"}
    llm_response = (
        f"File: {llm_filename}\n"
        "<<<<<<< SEARCH\n"
        "import os\n"
        "=======\n"
        "import sys\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated with various filename conventions
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the correct file is identified and patched
    assert "--- a/src/app/main.py" in diff
    assert "+++ b/src/app/main.py" in diff
    assert "-import os" in diff
    assert "+import sys" in diff


def test_patch_failure_when_search_block_not_found() -> None:
    # GIVEN a SEARCH block that doesn't exist in the original content
    original_contents = {"file.py": "original content"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "non-existent content\n"
        "=======\n"
        "new content\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN a failed patch diff is returned with an error
    assert "a/file.py" in diff
    assert "b/file.py (patch failed)" in diff
    assert "Error: The SEARCH block from the AI could not be found" in diff
    assert "--- SEARCH BLOCK ---" in diff
    assert "non-existent content" in diff
    assert "--- END SEARCH BLOCK ---" in diff


def test_error_when_file_not_found_in_context() -> None:
    # GIVEN an LLM response for a file not in the context
    original_contents = {"real_file.py": "content"}
    llm_response = (
        "File: unknown_file.py\n"
        "<<<<<<< SEARCH\n"
        "a\n"
        "=======\n"
        "b\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN a 'not found' diff is generated
    assert "a/unknown_file.py (not found)" in diff
    assert "b/unknown_file.py (not found)" in diff
    assert (
        "Error: The file path 'unknown_file.py' from the AI does not match any file in the context."
        in diff
    )


@pytest.mark.parametrize(
    "malformed_response,expected_error_header",
    [
        ("Just some conversational text.", "LLM_RESPONSE_ERROR"),
        ("File: file.py\nSome malformed content without blocks.", "MALFORMED_BLOCK"),
    ],
)
def test_handling_of_malformed_llm_responses(
    malformed_response: str, expected_error_header: str
) -> None:
    # GIVEN a malformed LLM response
    # WHEN the diff is generated
    diff = generate_diff_from_response({}, malformed_response)

    # THEN a diff is produced indicating the parsing error
    assert f"--- a/{expected_error_header}" in diff
    assert "Could not" in diff  # Check for error message body


def test_multi_block_llm_response() -> None:
    # GIVEN original contents for two files and a multi-block response
    original_contents = {
        "file_one.py": "one",
        "file_two.py": "two",
    }
    llm_response = (
        "File: file_one.py\n"
        "<<<<<<< SEARCH\n"
        "one\n"
        "=======\n"
        "1\n"
        ">>>>>>> REPLACE\n"
        "File: file_two.py\n"
        "<<<<<<< SEARCH\n"
        "two\n"
        "=======\n"
        "2\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the output contains two complete, valid diffs
    assert "--- a/file_one.py" in diff
    assert "+++ b/file_one.py" in diff
    assert "-one" in diff
    assert "+1" in diff

    assert "--- a/file_two.py" in diff
    assert "+++ b/file_two.py" in diff
    assert "-two" in diff
    assert "+2" in diff


def test_ambiguous_filepath_fails() -> None:
    # GIVEN multiple files with the same basename
    original_contents = {
        "src/api/utils.py": "api stuff",
        "src/core/utils.py": "core stuff",
    }
    llm_response = (
        "File: utils.py\n"
        "<<<<<<< SEARCH\n"
        "api stuff\n"
        "=======\n"
        "new api stuff\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated with the ambiguous basename
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN an ambiguity error is reported
    assert "a/utils.py (ambiguous match)" in diff
    assert "is ambiguous and matches multiple files" in diff


def test_ambiguous_patch_fails() -> None:
    # GIVEN a file where the target code block appears twice
    original_contents = {
        "file.py": "repeatable_line = 1\n\nrepeatable_line = 1\n"
    }
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "repeatable_line = 1\n"
        "=======\n"
        "changed_line = 2\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN an ambiguity error is reported
    assert "b/file.py (patch failed)" in diff
    assert "The SEARCH block is ambiguous and was found multiple times" in diff


def test_patching_with_blank_lines_in_search_block() -> None:
    # GIVEN a search block containing blank lines
    original_contents = {"file.py": "line one\n\nline three"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "line one\n"
        "\n"
        "line three\n"
        "=======\n"
        "replacement\n"
        ">>>>>>> REPLACE"
    )
    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the patch applies successfully
    assert "patch failed" not in diff
    assert "-line one" in diff
    assert "+replacement" in diff


def test_patch_that_changes_indentation() -> None:
    # GIVEN code that needs to be indented
    original_contents = {"file.py": "to_be_indented()"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "to_be_indented()\n"
        "=======\n"
        "if True:\n"
        "    to_be_indented()\n"
        ">>>>>>> REPLACE"
    )
    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the diff is generated correctly
    assert "patch failed" not in diff
    assert "+    to_be_indented()" in diff


def test_patch_that_outdents_code() -> None:
    # GIVEN a file with code inside an if block
    original_contents = {"file.py": "if True:\n    code_to_outdent()\n"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "if True:\n"
        "    code_to_outdent()\n"
        "=======\n"
        "code_to_outdent()\n"
        ">>>>>>> REPLACE"
    )
    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the patch applies correctly, with the code now outdented
    assert "patch failed" not in diff
    assert "-if True:" in diff
    assert "-    code_to_outdent()" in diff
    assert "+code_to_outdent()" in diff


def test_patch_for_multi_line_indent() -> None:
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
    diff = generate_diff_from_response(original_contents, llm_response)

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


def test_partial_deletion_inside_file() -> None:
    # GIVEN a file with a function and an AI patch to remove lines from it
    original_contents = {
        "file.py": "def my_func():\n    line_one = 1\n    line_two = 2\n    line_three = 3\n"
    }
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "    line_one = 1\n"
        "    line_two = 2\n"
        "=======\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the diff removes only those lines, leaving the surrounding context
    assert "patch failed" not in diff
    assert "def my_func()" in diff
    assert "-    line_one = 1" in diff
    assert "-    line_two = 2" in diff
    assert "    line_three = 3" in diff
    assert "+    " not in diff


def test_empty_search_on_existing_file_fails() -> None:
    # GIVEN an existing, non-empty file and an invalid AI patch with an empty search block
    original_contents = {"file.py": "some_content = True"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "=======\n"
        "new_content = False\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN it fails with a patch failed error because this is invalid for an existing file
    assert "patch failed" in diff
    assert "The SEARCH block from the AI could not be found" in diff


def test_patch_robust_to_delimiters_in_content() -> None:
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
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the patch is applied successfully, proving the parser's robustness
    assert "patch failed" not in diff
    assert "+content was changed" in diff
    assert "-<<<<<<< SEARCH" in diff


def test_patch_with_inconsistent_trailing_newlines() -> None:
    # GIVEN a source file with a trailing newline and an AI SEARCH block without one
    original_contents = {"file.py": "line1\nline2\n"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "line1\n"
        "line2\n"
        "=======\n"
        "line1\n"
        "line_two_changed\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the patch applies successfully due to flexible matching
    assert "patch failed" not in diff
    assert "-line2" in diff
    assert "+line_two_changed" in diff


def test_whitespace_only_change() -> None:
    # GIVEN a file with code separated by one blank line and a patch to add another
    original_contents = {"file.py": "line_one\n\nline_three"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "line_one\n"
        "\n"
        "line_three\n"
        "=======\n"
        "line_one\n"
        "\n"
        "\n"
        "line_three\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the diff correctly shows the addition of one blank line
    assert "patch failed" not in diff
    diff_lines = diff.splitlines()
    added_lines = [
        line for line in diff_lines if line.startswith("+") and "+++" not in line
    ]
    # The change from the original content to the new content is one added blank line.
    assert len(added_lines) == 1
    assert added_lines[0] == "+"


def test_mismatched_line_endings_patch_succeeds() -> None:
    # GIVEN a source file with CRLF endings and an AI patch with LF endings
    original_contents = {"file.py": "line1\r\nline2\r\n"}
    llm_response = (
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "line1\n"
        "line2\n"
        "=======\n"
        "new_line1\n"
        "new_line2\n"
        ">>>>>>> REPLACE"
    )

    # WHEN the diff is generated
    diff = generate_diff_from_response(original_contents, llm_response)

    # THEN the patch applies successfully because line endings are normalized for comparison
    assert "patch failed" not in diff
    assert "-line1" in diff
    assert "-line2" in diff
    assert "+new_line1" in diff
    assert "+new_line2" in diff
