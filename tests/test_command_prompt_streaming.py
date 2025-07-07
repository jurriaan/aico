# pyright: standard

from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.main import app

runner = CliRunner()


def _create_mock_stream_chunk(content: str | None, mocker: MockerFixture, usage: object | None = None) -> object:
    """Creates a mock stream chunk that conforms to the LiteLLMChoiceContainer protocol."""
    mock_delta = mocker.MagicMock()
    mock_delta.content = content

    mock_choice = mocker.MagicMock()
    mock_choice.delta = mock_delta

    mock_chunk = mocker.MagicMock()
    mock_chunk.choices = [mock_choice]
    mock_chunk.usage = usage
    return mock_chunk


def setup_streaming_test(
    mocker: MockerFixture,
    tmp_path: Path,
    llm_response_chunks: list[str],
    context_files: dict[str, str] | None = None,
) -> MockerFixture:
    """A helper to handle the common GIVEN steps for prompt command tests."""
    runner.invoke(app, ["init"])

    if context_files:
        for filename, content in context_files.items():
            (tmp_path / filename).write_text(content)
            runner.invoke(app, ["add", filename])

    mock_completion = mocker.patch("litellm.completion")

    mock_chunks = [_create_mock_stream_chunk(content, mocker=mocker) for content in llm_response_chunks]

    mock_stream = mocker.MagicMock()
    mock_stream.__iter__.return_value = iter(mock_chunks)
    mock_stream.usage = mocker.MagicMock()
    mock_stream.usage.prompt_tokens = 100
    mock_stream.usage.completion_tokens = 20
    mock_stream.usage.total_tokens = 120
    mock_completion.return_value = mock_stream
    mocker.patch("litellm.completion_cost", return_value=0.001)

    return mock_completion


def _run_multiple_patches_test(
    tmp_path: Path,
    mocker: MockerFixture,
    is_tty: bool,
) -> None:
    # GIVEN a file with multiple lines
    file_content = "line1\nline2\nline3\n"
    context_files = {"file.py": file_content}
    mocker.patch("aico.commands.prompt.is_terminal", return_value=is_tty)

    # AND an LLM response stream that contains two separate SEARCH/REPLACE blocks for the same file,
    # where the second block is missing a "File:" header. This triggers the bug in the live renderer.
    llm_response_chunks = [
        "File: file.py\n"
        "<<<<<<< SEARCH\n"
        "line1\n"
        "=======\n"
        "line_one_modified\n"
        ">>>>>>> REPLACE\n"
        "\n"
        "Some conversational text between patches.\n"
        "\n"
        "<<<<<<< SEARCH\n"
        "line3\n"
        "=======\n"
        "line_three_modified\n"
        ">>>>>>> REPLACE\n"
    ]

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_streaming_test(mocker, Path(td), llm_response_chunks, context_files=context_files)

        # WHEN `aico edit` is run
        result = runner.invoke(app, ["edit", "a prompt"])

        # THEN the command should succeed
        assert result.exit_code == 0, result.stderr

        # AND the output should be correct for the environment
        if is_tty:
            # For TTY, the live-rendered output should show a combined diff
            output = result.stdout
            assert "line_one_modified" in output
            assert "line_three_modified" in output
            assert "-line1" in output
            assert "+line_one_modified" in output
            assert "-line3" in output
            assert "+line_three_modified" in output
            assert "⚠️" not in output  # There should be no warnings about failed patches
        else:
            # For piped output, the final processed diff should be correct
            expected_diff = (
                "--- a/file.py\n"
                "+++ b/file.py\n"
                "@@ -1,3 +1,3 @@\n"
                "-line1\n"
                "+line_one_modified\n"
                " line2\n"
                "-line3\n"
                "+line_three_modified\n"
            )
            assert result.stdout == expected_diff


def test_streaming_handles_multiple_patches_for_same_file_tty(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    This test captures the live rendering bug.
    It WILL FAIL with the current implementation and will pass once the fix is implemented.
    """
    _run_multiple_patches_test(tmp_path, mocker, is_tty=True)


def test_streaming_handles_multiple_patches_for_same_file_piped(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    This test validates the final processing logic.
    It should PASS with the current implementation, as the bug is in live rendering,
    not in the sequential processing that generates the final piped output.
    """
    _run_multiple_patches_test(tmp_path, mocker, is_tty=False)


def test_streaming_renders_failed_diff_block_as_plain_text(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a TTY environment and a file
    file_content = "original content\n"
    context_files = {"file.py": file_content}
    mocker.patch("aico.commands.prompt.is_terminal", return_value=True)

    # AND an LLM response stream containing a SEARCH/REPLACE block that will fail to apply
    llm_response_chunks = [
        "This is some conversational text.\n",
        "File: file.py\n",
        "<<<<<<< SEARCH\n",
        "some text not in file\n",
        "=======\n",
        "new content\n",
        ">>>>>>> REPLACE\n",
        "Some final text.",
    ]

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_streaming_test(mocker, Path(td), llm_response_chunks, context_files=context_files)

        # WHEN `aico edit` is run
        result = runner.invoke(app, ["edit", "a prompt that will fail"])

        # THEN the command should succeed
        assert result.exit_code == 0, result.stderr

        # AND the output contains all expected text elements
        output = result.stdout
        raw_block_text = "<<<<<<< SEARCH\nsome text not in file\n=======\nnew content\n>>>>>>> REPLACE"
        assert "This is some conversational text." in output
        assert "⚠️" in output
        assert "The SEARCH block from the AI could not be found" in output
        assert raw_block_text in output
        assert "Some final text." in output


def test_streaming_renders_incomplete_diff_block_as_plain_text(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a TTY environment and a file
    mocker.patch("aico.commands.prompt.is_terminal", return_value=True)

    # AND an LLM response stream that cuts off in the middle of a SEARCH/REPLACE block
    llm_response_chunks = [
        "File: file.py\n",
        "<<<<<<< SEARCH\n",
        "some text\n",
        "=======\n",
        "# new content that is never finished",
    ]

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_streaming_test(mocker, Path(td), llm_response_chunks, context_files={"file.py": "some text\n"})

        # WHEN `aico edit` is run
        result = runner.invoke(app, ["edit", "a prompt that will be cut off"])

        # THEN the command should succeed
        assert result.exit_code == 0, result.stderr

        # AND the output should contain the raw, incomplete block
        output = result.stdout
        expected_incomplete_text = "<<<<<<< SEARCH\nsome text\n=======\n# new content that is never finished"
        assert expected_incomplete_text in output
