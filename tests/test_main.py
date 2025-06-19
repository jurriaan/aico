import json
import os
from pathlib import Path

from typer.testing import CliRunner

from aico.main import app
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def test_init_creates_session_file_in_empty_dir(tmp_path: Path) -> None:
    # GIVEN a directory without a session file
    # We use pytest's tmp_path fixture and run the command within that isolated directory.
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # WHEN `aico init` is run
        result = runner.invoke(app, ["init"])

        # THEN the command succeeds and creates the session file
        assert result.exit_code == 0
        session_file = Path(td) / SESSION_FILE_NAME
        assert session_file.is_file()
        assert f"Initialized session file: {session_file}" in result.stdout

        # AND the session file contains the default model
        assert (
            '"model": "openrouter/google/gemini-2.5-pro"' in session_file.read_text()
        )


def test_init_fails_if_session_already_exists(tmp_path: Path) -> None:
    # GIVEN a directory with an existing session file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        expected_path = Path(td) / SESSION_FILE_NAME
        expected_path.touch()

        # WHEN `aico init` is run again
        result = runner.invoke(app, ["init"])

        # THEN the command fails with an appropriate error message
        assert result.exit_code == 1

        assert (
            f"Error: An existing session was found at '{expected_path}'"
            in result.stderr
        )


def test_init_fails_if_session_exists_in_parent_dir(tmp_path: Path) -> None:
    # GIVEN a session file exists in a parent directory
    (tmp_path / SESSION_FILE_NAME).touch()
    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()

    original_cwd = os.getcwd()
    try:
        os.chdir(sub_dir)
        # WHEN `aico init` is run from the subdirectory
        result = runner.invoke(app, ["init"])

        # THEN the command fails with an error message about the found session
        assert result.exit_code == 1
        expected_path = tmp_path / SESSION_FILE_NAME
        assert (
            f"Error: An existing session was found at '{expected_path}'"
            in result.stderr
        )
    finally:
        os.chdir(original_cwd)


def test_add_file_to_context(tmp_path: Path) -> None:
    # GIVEN an initialized session and a file to add
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        test_file = Path(td) / "test_file.py"
        test_file.write_text("print('hello')")

        # WHEN `aico add` is run with the file path
        result = runner.invoke(app, ["add", "test_file.py"])

        # THEN the command succeeds and reports the addition
        assert result.exit_code == 0
        assert "Added file to context: test_file.py" in result.stdout

        # AND the session file is updated with the file's relative path
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert session_data["context_files"] == ["test_file.py"]


def test_add_duplicate_file_is_ignored(tmp_path: Path) -> None:
    # GIVEN a session with a file already in the context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        test_file = Path(td) / "test_file.py"
        test_file.write_text("print('hello')")
        # Add it once
        runner.invoke(app, ["add", str(test_file)])

        # WHEN the same file is added again
        result = runner.invoke(app, ["add", str(test_file)])

        # THEN the command reports that the file is already in context
        assert result.exit_code == 0
        assert "File already in context: test_file.py" in result.stdout

        # AND the session context list remains unchanged
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert session_data["context_files"] == ["test_file.py"]


def test_add_non_existent_file_fails(tmp_path: Path) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN adding a file that does not exist
        result = runner.invoke(app, ["add", "non_existent_file.py"])

        # THEN the command fails with an error
        assert result.exit_code == 1
        assert "Error: File not found: non_existent_file.py" in result.stderr


def test_add_file_outside_session_root_fails(tmp_path: Path) -> None:
    # GIVEN a session in one directory and a file in a parallel directory
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    other_dir = tmp_path / "other"
    other_dir.mkdir()

    other_file = other_dir / "file.txt"
    other_file.touch()

    with runner.isolated_filesystem(temp_dir=project_dir) as td:
        runner.invoke(app, ["init"])

        # WHEN attempting to add the file using a path that goes outside the session root
        # Note: We resolve the path to be absolute to test the logic robustly.
        result = runner.invoke(app, ["add", str(other_file.resolve())])

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert (
            f"Error: File '{other_file.resolve()}' is outside the session root '{Path(td).resolve()}'"
            in result.stderr
        )


def test_last_prints_last_response(tmp_path: Path) -> None:
    # GIVEN a session file with a last_response object
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = {
            "model": "test-model",
            "last_response": {
                "raw_content": "raw",
                "mode_used": "raw",
                "processed_content": "This is the processed content.",
            },
        }
        session_file.write_text(json.dumps(session_data))

        # WHEN `aico last` is run
        result = runner.invoke(app, ["last"])

        # THEN the processed content is printed to stdout
        assert result.exit_code == 0
        assert "This is the processed content." in result.stdout


def test_last_fails_when_no_last_response_exists(tmp_path: Path) -> None:
    # GIVEN a session file with no last_response
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN `aico last` is run
        result = runner.invoke(app, ["last"])

        # THEN the command fails with an error
        assert result.exit_code == 1
        assert "Error: No last response found in session." in result.stderr


def test_prompt_raw_mode(tmp_path: Path, mocker) -> None:
    # GIVEN a session with a context file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        code_file = Path(td) / "code.py"
        code_file.write_text("def hello():\n    pass")
        runner.invoke(app, ["add", "code.py"])

        # AND the LLM API is mocked
        mock_completion = mocker.patch("litellm.completion")
        mock_response = mocker.MagicMock()
        mock_response.choices[0].message.content = "This is a raw response."
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 120
        mock_completion.return_value = mock_response

        mocker.patch("litellm.completion_cost", return_value=0.001)

        # WHEN `aico prompt --mode raw` is run
        prompt_text = "Explain this code"
        result = runner.invoke(app, ["prompt", "--mode", "raw", prompt_text])

        # THEN the command succeeds and prints the raw response
        # Note: We don't need to mock rich, as CliRunner's stdout is not a TTY,
        # so the raw content is printed directly.
        assert result.exit_code == 0
        assert "This is a raw response." in result.stdout

        # AND the API was called with the correct context and prompt
        mock_completion.assert_called_once()
        # The `messages` are passed as a keyword argument to litellm.completion
        call_kwargs = mock_completion.call_args.kwargs
        messages = call_kwargs["messages"]

        system_message = messages[0]["content"]
        user_message = messages[-1]["content"]

        assert "You are an expert pair programmer." in system_message
        assert '<file path="code.py">\ndef hello():\n    pass\n</file>' in user_message
        assert f"<prompt>\n{prompt_text}\n</prompt>" in user_message

        # AND it prints token and cost info to stderr
        assert "Tokens: 100 sent, 20 received." in result.stderr
        assert "Cost: $0.00 message" in result.stderr

        # AND the session history is updated
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())

        assert len(session_data["chat_history"]) == 2
        assert session_data["chat_history"][0]["role"] == "user"
        assert session_data["chat_history"][0]["content"] == prompt_text
        assert session_data["chat_history"][1]["role"] == "assistant"
        assert session_data["chat_history"][1]["content"] == "This is a raw response."
        assert session_data["last_response"]["raw_content"] == "This is a raw response."


def test_prompt_diff_mode(tmp_path: Path, mocker) -> None:
    # GIVEN a session with a context file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        code_file = Path(td) / "code.py"
        original_content = "def hello():\n    pass"
        code_file.write_text(original_content)
        runner.invoke(app, ["add", "code.py"])

        # AND the LLM API is mocked to return a valid diff response
        llm_diff_response = (
            "File: code.py\n"
            "<<<<<<< SEARCH\n"
            "def hello():\n"
            "    pass\n"
            "=======\n"
            'def hello(name: str):\n'
            "    print(f'Hello, {name}!')\n"
            ">>>>>>> REPLACE"
        )
        mock_completion = mocker.patch("litellm.completion")
        mock_response = mocker.MagicMock()
        mock_response.choices[0].message.content = llm_diff_response
        mock_response.usage.prompt_tokens = 150
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 200
        mock_completion.return_value = mock_response
        mocker.patch("litellm.completion_cost", return_value=0.002)

        # WHEN `aico prompt --mode diff` is run
        prompt_text = "Add a name parameter and print it"
        result = runner.invoke(app, ["prompt", "--mode", "diff", prompt_text])

        # THEN the command succeeds and prints a valid unified diff
        assert result.exit_code == 0
        assert "--- a/code.py" in result.stdout
        assert "+++ b/code.py" in result.stdout
        assert "-def hello():" in result.stdout
        assert "-    pass" in result.stdout
        assert "+def hello(name: str):" in result.stdout
        assert "+    print(f'Hello, {name}!')" in result.stdout

        # AND the session history is updated
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert len(session_data["chat_history"]) == 2
        assert session_data["last_response"]["raw_content"] == llm_diff_response
        assert (
            session_data["last_response"]["processed_content"] == result.stdout.strip()
        )
