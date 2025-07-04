# pyright: standard

from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.main import app

runner = CliRunner()


def _create_mock_stream_chunk(content: str | None, mocker: MockerFixture) -> object:
    """Creates a mock stream chunk that conforms to the LiteLLMChoiceContainer protocol."""
    mock_delta = mocker.MagicMock()
    mock_delta.content = content

    mock_choice = mocker.MagicMock()
    mock_choice.delta = mock_delta

    mock_chunk = mocker.MagicMock()
    mock_chunk.choices = [mock_choice]
    return mock_chunk


def setup_piping_test(
    mocker: MockerFixture,
    tmp_path: Path,
    llm_response_content: str,
    context_files: dict[str, str] | None = None,
) -> None:
    """A helper to handle the common GIVEN steps for prompt piping tests."""
    runner.invoke(app, ["init"])

    if context_files:
        for filename, content in context_files.items():
            (tmp_path / filename).write_text(content)
            runner.invoke(app, ["add", filename])

    # For these tests, we are always in a non-TTY (piped) environment
    mocker.patch("aico.commands.prompt.is_terminal", return_value=False)

    mock_completion = mocker.patch("litellm.completion")
    mock_chunk = _create_mock_stream_chunk(llm_response_content, mocker=mocker)
    mock_stream = mocker.MagicMock()
    mock_stream.__iter__.return_value = iter([mock_chunk])
    # The usage data is an attribute of the stream, not the chunk
    mock_stream.usage = mocker.MagicMock()
    mock_stream.usage.prompt_tokens = 10
    mock_stream.usage.completion_tokens = 10
    mock_stream.usage.total_tokens = 20
    mock_completion.return_value = mock_stream

    # Mock cost calculation to avoid API calls
    mocker.patch("litellm.completion_cost", return_value=0.001)


def test_edit_successful_diff_piped(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    Tests the 'Strict Contract' for `aico edit`: successful diffs are printed to stdout.
    """
    # GIVEN a session with a file and a mocked LLM returning a valid diff
    llm_response = "File: file.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE"
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_piping_test(mocker, Path(td), llm_response, context_files={"file.py": "old content"})

        # WHEN `aico edit` is run
        result = runner.invoke(app, ["edit", "a prompt"])

        # THEN the command succeeds
        assert result.exit_code == 0
        # AND stdout contains ONLY the clean, unified diff
        expected_diff = (
            "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old content\n\\ No newline at end of file\n+new content\n"
        )
        assert result.stdout == expected_diff
        # AND stderr contains cost info but no warnings
        assert "Cost:" in result.stderr
        assert "Warning" not in result.stderr


def test_edit_failing_diff_piped(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    Tests the 'Strict Contract' for `aico edit`: failing diffs result in an empty stdout.
    """
    # GIVEN a session with a file and a mocked LLM returning a failing diff
    llm_response = "File: file.py\n<<<<<<< SEARCH\ncontent not found\n=======\nnew content\n>>>>>>> REPLACE"
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_piping_test(mocker, Path(td), llm_response, context_files={"file.py": "old content"})

        # WHEN `aico edit` is run
        result = runner.invoke(app, ["edit", "a prompt"])

        # THEN the command succeeds
        assert result.exit_code == 0
        # AND stdout is an empty string
        assert result.stdout == ""
        # AND stderr contains the warning about the patch failure
        assert "Warnings:" in result.stderr
        assert "The SEARCH block from the AI could not be found" in result.stderr


def test_ask_conversational_text_piped(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    Tests the 'Flexible Contract' for `aico ask`: conversational text is printed to stdout.
    """
    # GIVEN a session and an LLM returning plain text
    llm_response = "This is a simple conversational response."
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_piping_test(mocker, Path(td), llm_response)

        # WHEN `aico ask` is run
        result = runner.invoke(app, ["ask", "a prompt"])

        # THEN the command succeeds
        assert result.exit_code == 0
        # AND stdout contains the conversational text
        assert result.stdout == llm_response


def test_ask_successful_diff_piped(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    Tests the 'Flexible Contract' for `aico ask`: a successful diff is prioritized and printed to stdout.
    """
    # GIVEN a session, a file, and an LLM returning a valid diff
    llm_response = "File: file.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE"
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_piping_test(mocker, Path(td), llm_response, context_files={"file.py": "old content"})

        # WHEN `aico ask` is run
        result = runner.invoke(app, ["ask", "a prompt"])

        # THEN the command succeeds
        assert result.exit_code == 0
        # AND stdout contains the clean, unified diff
        expected_diff = (
            "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old content\n\\ No newline at end of file\n+new content\n"
        )
        assert result.stdout == expected_diff


def test_ask_failing_diff_piped(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    Tests the 'Flexible Contract' for `aico ask`: a failing diff falls back to printing the `display_content` to stdout.
    """
    # GIVEN a session, a file, and an LLM returning a failing diff
    llm_response = "File: file.py\n<<<<<<< SEARCH\ncontent not found\n=======\nnew content\n>>>>>>> REPLACE"
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_piping_test(mocker, Path(td), llm_response, context_files={"file.py": "old content"})

        # WHEN `aico ask` is run
        result = runner.invoke(app, ["ask", "a prompt"])

        # THEN the command succeeds
        assert result.exit_code == 0
        # AND stdout contains the fallback display_content with the rich error
        assert "The SEARCH block from the AI could not be found" in result.stdout
        assert "```diff" not in result.stdout  # The raw block is shown, not a diff
        assert "<<<<<<< SEARCH" in result.stdout
        # AND stderr contains the warning as well
        assert "Warnings:" in result.stderr
        assert "The SEARCH block from the AI could not be found" in result.stderr
