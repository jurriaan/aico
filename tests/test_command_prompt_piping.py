# pyright: standard

from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.main import app
from aico.models import TokenUsage
from tests import helpers

runner = CliRunner()


def test_gen_successful_diff_piped(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    Tests the 'Strict Contract' for `aico gen`: successful diffs are printed to stdout.
    """
    # GIVEN a session with a file and a mocked LLM returning a valid diff
    llm_response = "File: file.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE"
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # For these tests, we are always in a non-TTY (piped) environment
        mocker.patch("aico.commands.prompt.is_terminal", return_value=False)
        mocker.patch("aico.llm.executor.is_terminal", return_value=False)

        usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20, cost=0.005)

        helpers.setup_test_session_and_llm(
            runner,
            app,
            Path(td),
            mocker,
            llm_response,
            context_files={"file.py": "old content"},
            usage=usage,
        )

        # WHEN `aico gen` is run
        result = runner.invoke(app, ["gen", "a prompt"])

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


def test_gen_failing_diff_piped(tmp_path: Path, mocker: MockerFixture) -> None:
    """
    Tests the 'Strict Contract' for `aico gen`: failing diffs result in an empty stdout.
    """
    # GIVEN a session with a file and a mocked LLM returning a failing diff
    llm_response = "File: file.py\n<<<<<<< SEARCH\ncontent not found\n=======\nnew content\n>>>>>>> REPLACE"
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        mocker.patch("aico.commands.prompt.is_terminal", return_value=False)
        mocker.patch("aico.llm.executor.is_terminal", return_value=False)
        usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20, cost=0.005)

        helpers.setup_test_session_and_llm(
            runner,
            app,
            Path(td),
            mocker,
            llm_response,
            context_files={"file.py": "old content"},
            usage=usage,
        )

        # WHEN `aico gen` is run
        result = runner.invoke(app, ["gen", "a prompt"])

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
        mocker.patch("aico.commands.prompt.is_terminal", return_value=False)
        mocker.patch("aico.llm.executor.is_terminal", return_value=False)
        usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20, cost=0.005)

        helpers.setup_test_session_and_llm(runner, app, Path(td), mocker, llm_response, usage=usage)

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
        mocker.patch("aico.commands.prompt.is_terminal", return_value=False)
        mocker.patch("aico.llm.executor.is_terminal", return_value=False)
        usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20, cost=0.005)

        helpers.setup_test_session_and_llm(
            runner,
            app,
            Path(td),
            mocker,
            llm_response,
            context_files={"file.py": "old content"},
            usage=usage,
        )

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
        mocker.patch("aico.commands.prompt.is_terminal", return_value=False)
        mocker.patch("aico.llm.executor.is_terminal", return_value=False)
        usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20, cost=0.005)

        helpers.setup_test_session_and_llm(
            runner,
            app,
            Path(td),
            mocker,
            llm_response,
            context_files={"file.py": "old content"},
            usage=usage,
        )

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
