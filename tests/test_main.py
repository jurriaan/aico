import json
import os
from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.main import app, complete_files_in_context
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def _create_mock_stream_chunk(
    content: str | None, mocker: MockerFixture, usage: object | None = None
) -> object:
    """
    Creates a mock stream chunk that conforms to the LiteLLMChoiceContainer
    and LiteLLMUsageContainer protocols.
    """
    mock_delta = mocker.MagicMock()
    mock_delta.content = content

    mock_choice = mocker.MagicMock()
    mock_choice.delta = mock_delta

    mock_chunk = mocker.MagicMock()
    mock_chunk.choices = [mock_choice]
    mock_chunk.usage = usage
    return mock_chunk


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
        assert '"model": "openrouter/google/gemini-2.5-pro"' in session_file.read_text()


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


# --- Tests for the `last` command ---
# Test data for a response that was `conversation` but contained a diff
DIFF_IN_CONVERSATION_RESPONSE = {
    "raw_content": "File: a.py\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE",
    "mode_used": "conversation",
    "unified_diff": "--- a/a.py\n+++ b/a.py\n-old\n+new",
    "display_content": "File: a.py\n```diff\n--- a/a.py\n+++ b/a.py\n-old\n+new\n```\n",
    "model": "test-model",
    "timestamp": "2024-01-01T00:00:00Z",
    "duration_ms": 123,
}

# Test data for a response that was just conversational
CONVERSATIONAL_RESPONSE = {
    "raw_content": "Hello there!",
    "mode_used": "conversation",
    "unified_diff": "",
    "display_content": "Hello there!",
    "model": "test-model",
    "timestamp": "2024-01-01T00:00:00Z",
    "duration_ms": 123,
}


def _create_session_with_last_response(
    tmp_path: Path, last_response_data: dict
) -> None:
    """Helper to create a session file in a temp directory."""
    session_file = tmp_path / SESSION_FILE_NAME
    session_data = {
        "model": "test-model",
        "history_start_index": 0,
        "context_files": [],
        "chat_history": [],
        "last_response": last_response_data,
    }
    session_file.write_text(json.dumps(session_data))


def test_last_smart_default_shows_parsed_diff_in_tty(tmp_path: Path, mocker) -> None:
    # GIVEN a session where the last response contained a diff
    _create_session_with_last_response(tmp_path, DIFF_IN_CONVERSATION_RESPONSE)
    mocker.patch("aico.main.is_terminal", return_value=True)

    # WHEN `aico last` is run in a TTY
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["last"])

    # THEN the pretty diff (`display_content`) is shown
    assert result.exit_code == 0
    # Check for the content inside the rendered diff, not the markdown syntax
    assert "--- a/a.py" in result.stdout
    assert "-old" in result.stdout
    assert "+new" in result.stdout
    assert DIFF_IN_CONVERSATION_RESPONSE["raw_content"] not in result.stdout


def test_last_smart_default_falls_back_to_raw_in_tty(tmp_path: Path, mocker) -> None:
    # GIVEN a session where the last response was purely conversational
    _create_session_with_last_response(tmp_path, CONVERSATIONAL_RESPONSE)
    mocker.patch("aico.main.is_terminal", return_value=True)

    # WHEN `aico last` is run in a TTY
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["last"])

    # THEN the raw content is shown (as it's the best available)
    assert result.exit_code == 0
    assert "Hello there!" in result.stdout
    assert "```diff" not in result.stdout


def test_last_smart_default_shows_unified_diff_when_piped(
    tmp_path: Path, mocker
) -> None:
    # GIVEN a session where the last response contained a diff
    _create_session_with_last_response(tmp_path, DIFF_IN_CONVERSATION_RESPONSE)
    mocker.patch("aico.main.is_terminal", return_value=False)

    # WHEN `aico last` is piped
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["last"])

    # THEN the clean `unified_diff` is printed
    assert result.exit_code == 0
    assert result.stdout.strip() == DIFF_IN_CONVERSATION_RESPONSE["unified_diff"]


def test_last_verbatim_shows_raw_content_in_tty(tmp_path: Path, mocker) -> None:
    # GIVEN a session with a diff-containing response
    _create_session_with_last_response(tmp_path, DIFF_IN_CONVERSATION_RESPONSE)
    mocker.patch("aico.main.is_terminal", return_value=True)

    # WHEN `aico last --verbatim` is run in a TTY
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["last", "--verbatim"])

    # THEN the original raw response is shown
    assert result.exit_code == 0
    assert "<<<<<<< SEARCH" in result.stdout


def test_last_verbatim_shows_raw_content_when_piped(tmp_path: Path, mocker) -> None:
    # GIVEN a session with a diff-containing response
    _create_session_with_last_response(tmp_path, DIFF_IN_CONVERSATION_RESPONSE)
    mocker.patch("aico.main.is_terminal", return_value=False)

    # WHEN `aico last --verbatim` is piped
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["last", "--verbatim"])

    # THEN the raw content is printed without modification
    assert result.exit_code == 0
    assert result.stdout.strip() == DIFF_IN_CONVERSATION_RESPONSE["raw_content"]


def test_last_fails_when_no_last_response_exists(tmp_path: Path) -> None:
    # GIVEN a session file with no last_response
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN `aico last` is run
        result = runner.invoke(app, ["last"])

        # THEN the command fails with an error
        assert result.exit_code == 1
        assert "Error: No last response found in session." in result.stderr


def test_prompt_conversation_mode_injects_alignment(tmp_path: Path, mocker) -> None:
    # GIVEN a session with a context file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        code_file = Path(td) / "code.py"
        code_file.write_text("def hello():\n    pass")
        runner.invoke(app, ["add", "code.py"])

        # AND the LLM API is mocked to return a stream of chunks
        mock_completion = mocker.patch("litellm.completion")

        # Create a mock for the usage data, expected on a stream chunk
        mock_usage_obj = mocker.MagicMock()
        mock_usage_obj.prompt_tokens = 100
        mock_usage_obj.completion_tokens = 20
        mock_usage_obj.total_tokens = 120

        mock_chunk_1 = _create_mock_stream_chunk("This is a ", mocker=mocker)
        mock_chunk_2 = _create_mock_stream_chunk(
            "raw response.", mocker=mocker, usage=mock_usage_obj
        )

        mock_stream = mocker.MagicMock()
        mock_stream.__iter__.return_value = iter([mock_chunk_1, mock_chunk_2])
        mock_completion.return_value = mock_stream
        mocker.patch("litellm.completion_cost", return_value=0.001)

        # WHEN `aico prompt` is run (defaulting to conversation mode)
        prompt_text = "Explain this code"
        result = runner.invoke(app, ["prompt", prompt_text])

        # THEN the command succeeds and prints the raw response. This works because
        # the test runner's stdout is not a TTY, so our handler silently
        # accumulates the result, which is then printed by the main prompt command.
        assert result.exit_code == 0
        assert "This is a raw response." in result.stdout

        # AND the API was called with the correct context and prompt, including alignment
        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args.kwargs
        messages = call_kwargs["messages"]
        # system, history (0), align-user, align-asst, user
        assert len(messages) == 4

        system_message = messages[0]["content"]
        align_user_msg = messages[1]
        align_asst_msg = messages[2]
        user_message = messages[-1]["content"]

        assert "You are an expert pair programmer." in system_message
        assert align_user_msg["role"] == "user"
        assert "conversational assistant" in align_user_msg["content"]
        assert align_asst_msg["role"] == "assistant"
        assert "Understood" in align_asst_msg["content"]
        assert '<file path="code.py">\ndef hello():\n    pass\n</file>' in user_message
        assert f"<prompt>\n{prompt_text}\n</prompt>" in user_message

        # AND it prints token and cost info to stderr
        assert "Tokens: 100 sent, 20 received." in result.stderr
        assert "Cost: $0.00 message" in result.stderr

        # AND the session history is updated with the new rich models
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())

        assert len(session_data["chat_history"]) == 2
        user_msg = session_data["chat_history"][0]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == prompt_text
        assert user_msg["mode"] == "conversation"
        assert "timestamp" in user_msg

        assistant_msg = session_data["chat_history"][1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == "This is a raw response."
        assert assistant_msg["mode"] == "conversation"
        assert "timestamp" in assistant_msg
        assert assistant_msg["model"] == "openrouter/google/gemini-2.5-pro"
        assert assistant_msg["duration_ms"] > -1
        assert assistant_msg["token_usage"]["prompt_tokens"] == 100
        assert assistant_msg["cost"] is not None

        last_response = session_data["last_response"]
        assert last_response["raw_content"] == "This is a raw response."
        # For a truly conversational response, derived fields will be calculated but empty/same.
        assert last_response["unified_diff"] == ""
        assert last_response["display_content"] == "This is a raw response."

        # AND the new metadata is present
        assert last_response["model"] == "openrouter/google/gemini-2.5-pro"
        assert last_response["timestamp"] is not None
        assert last_response["duration_ms"] > -1
        assert last_response["token_usage"]["prompt_tokens"] == 100
        assert last_response["cost"] is not None


def test_prompt_diff_mode(tmp_path: Path, mocker) -> None:
    # GIVEN a session with a context file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        code_file = Path(td) / "code.py"
        original_content = "def hello():\n    pass"
        code_file.write_text(original_content)
        runner.invoke(app, ["add", "code.py"])

        # AND the LLM API is mocked to return a stream of chunks for a diff
        llm_diff_response = (
            "File: code.py\n"
            "<<<<<<< SEARCH\n"
            "def hello():\n"
            "    pass\n"
            "=======\n"
            "def hello(name: str):\n"
            "    print(f'Hello, {name}!')\n"
            ">>>>>>> REPLACE"
        )
        mock_completion = mocker.patch("litellm.completion")

        # Simulate the response being streamed in two parts
        mock_usage_obj = mocker.MagicMock()
        mock_usage_obj.prompt_tokens = 150
        mock_usage_obj.completion_tokens = 50
        mock_usage_obj.total_tokens = 200

        mock_chunk_1 = _create_mock_stream_chunk(llm_diff_response[:60], mocker=mocker)
        mock_chunk_2 = _create_mock_stream_chunk(
            llm_diff_response[60:], mocker=mocker, usage=mock_usage_obj
        )

        mock_stream = mocker.MagicMock()
        mock_stream.__iter__.return_value = iter([mock_chunk_1, mock_chunk_2])
        mock_completion.return_value = mock_stream
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

        # AND it prints token and cost info to stderr
        assert "Tokens: 150 sent, 50 received." in result.stderr
        assert "Cost: $0.00 message" in result.stderr

        # AND the session history is updated with the new rich models
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert len(session_data["chat_history"]) == 2
        user_msg = session_data["chat_history"][0]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == prompt_text
        assert user_msg["mode"] == "diff"
        assert "timestamp" in user_msg

        assistant_msg = session_data["chat_history"][1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == llm_diff_response
        assert assistant_msg["mode"] == "diff"
        assert assistant_msg["model"] == "openrouter/google/gemini-2.5-pro"
        assert assistant_msg["token_usage"]["prompt_tokens"] == 150
        assert assistant_msg["cost"] is not None
        assert "timestamp" in assistant_msg

        last_response = session_data["last_response"]
        assert last_response["raw_content"] == llm_diff_response
        assert last_response["unified_diff"] == result.stdout.strip()
        # Also check that display_content was generated and stored
        assert last_response["display_content"] is not None
        assert "```diff" in last_response["display_content"]

        # AND the new metadata is present
        assert last_response["model"] == "openrouter/google/gemini-2.5-pro"
        assert last_response["timestamp"] is not None
        assert last_response["duration_ms"] > -1
        assert last_response["token_usage"]["completion_tokens"] == 50
        assert last_response["cost"] is not None


def test_add_multiple_files_successfully(tmp_path: Path) -> None:
    # GIVEN an initialized session and two files to add
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        file1 = Path(td) / "file1.py"
        file1.write_text("content1")
        file2 = Path(td) / "file2.py"
        file2.write_text("content2")

        # WHEN `aico add` is run with multiple files
        result = runner.invoke(app, ["add", "file1.py", "file2.py"])

        # THEN the command succeeds and reports both additions
        assert result.exit_code == 0
        assert "Added file to context: file1.py" in result.stdout
        assert "Added file to context: file2.py" in result.stdout

        # AND the session file is updated with both relative paths
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert sorted(session_data["context_files"]) == ["file1.py", "file2.py"]


def test_add_multiple_files_with_one_already_in_context(tmp_path: Path) -> None:
    # GIVEN a session with one file already in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        file1 = Path(td) / "file1.py"
        file1.write_text("content1")
        file2 = Path(td) / "file2.py"
        file2.write_text("content2")
        runner.invoke(app, ["add", "file1.py"])  # Pre-add file1

        # WHEN `aico add` is run with both the existing and a new file
        result = runner.invoke(app, ["add", "file1.py", "file2.py"])

        # THEN the command succeeds and reports the correct status for each
        assert result.exit_code == 0
        assert "File already in context: file1.py" in result.stdout
        assert "Added file to context: file2.py" in result.stdout

        # AND the session file contains both files without duplicates
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert sorted(session_data["context_files"]) == ["file1.py", "file2.py"]


def test_add_multiple_files_with_one_non_existent_partially_fails(
    tmp_path: Path,
) -> None:
    # GIVEN an initialized session and one valid and one non-existent file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        file1 = Path(td) / "file1.py"
        file1.write_text("content1")
        non_existent_file = "non_existent.py"

        # WHEN `aico add` is run with both files
        result = runner.invoke(app, ["add", "file1.py", non_existent_file])

        # THEN the command exits with a non-zero status code
        assert result.exit_code == 1

        # AND it reports the success for the valid file
        assert "Added file to context: file1.py" in result.stdout

        # AND it reports an error for the non-existent file
        assert f"Error: File not found: {non_existent_file}" in result.stderr

        # AND the session file is updated with only the valid file
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert session_data["context_files"] == ["file1.py"]


def test_drop_single_file_successfully(tmp_path: Path) -> None:
    # GIVEN a session with two files in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        (Path(td) / "file1.py").touch()
        (Path(td) / "file2.py").touch()
        runner.invoke(app, ["add", "file1.py", "file2.py"])

        # WHEN `aico drop` is run on one file
        result = runner.invoke(app, ["drop", "file1.py"])

        # THEN the command succeeds and reports the removal
        assert result.exit_code == 0
        assert "Dropped file from context: file1.py" in result.stdout

        # AND the session file is updated to contain only the other file
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert sorted(session_data["context_files"]) == ["file2.py"]


def test_drop_multiple_files_successfully(tmp_path: Path) -> None:
    # GIVEN a session with three files in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        (Path(td) / "file1.py").touch()
        (Path(td) / "file2.py").touch()
        (Path(td) / "file3.py").touch()
        runner.invoke(app, ["add", "file1.py", "file2.py", "file3.py"])

        # WHEN `aico drop` is run on two files
        result = runner.invoke(app, ["drop", "file1.py", "file3.py"])

        # THEN the command succeeds and reports both removals
        assert result.exit_code == 0
        assert "Dropped file from context: file1.py" in result.stdout
        assert "Dropped file from context: file3.py" in result.stdout

        # AND the session file is updated correctly
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert sorted(session_data["context_files"]) == ["file2.py"]


def test_drop_file_not_in_context_fails(tmp_path: Path) -> None:
    # GIVEN a session with one file in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        (Path(td) / "file1.py").touch()
        runner.invoke(app, ["add", "file1.py"])

        # WHEN `aico drop` is run on a file not in the context
        result = runner.invoke(app, ["drop", "not_in_context.py"])

        # THEN the command fails with a non-zero exit code
        assert result.exit_code == 1

        # AND an error is printed to stderr
        assert "Error: File not in context: not_in_context.py" in result.stderr

        # AND the session file remains unchanged
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert session_data["context_files"] == ["file1.py"]


def test_prompt_raw_mode_does_not_inject_alignment(tmp_path: Path, mocker) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])
        mock_completion = mocker.patch("litellm.completion")
        mock_chunk = _create_mock_stream_chunk("raw output", mocker=mocker)
        mock_stream = mocker.MagicMock()
        mock_stream.__iter__.return_value = iter([mock_chunk])
        mock_completion.return_value = mock_stream
        mocker.patch("litellm.completion_cost", return_value=None)
        mocker.patch("litellm.token_counter", return_value=1)

        # WHEN `aico prompt --mode raw` is run
        result = runner.invoke(app, ["prompt", "--mode", "raw", "some prompt"])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the API was called without any alignment messages
        messages = mock_completion.call_args.kwargs["messages"]
        assert len(messages) == 2  # system, user
        message_contents = [m["content"] for m in messages]
        assert not any("conversational assistant" in c for c in message_contents)


def test_prompt_conversation_mode_with_diff_response_renders_live_diff(
    tmp_path: Path, mocker
) -> None:
    # GIVEN a TTY-enabled environment and a session with a context file
    mocker.patch("aico.main.is_terminal", return_value=True)

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        code_file = Path(td) / "code.py"
        original_content = "def hello():\n    pass"
        code_file.write_text(original_content)
        runner.invoke(app, ["add", "code.py"])

        # AND the LLM API is mocked to return a stream of chunks for a diff
        llm_diff_response = (
            "File: code.py\n"
            "<<<<<<< SEARCH\n"
            "def hello():\n"
            "    pass\n"
            "=======\n"
            "def hello(name: str):\n"
            "    print(f'Hello, {name}!')\n"
            ">>>>>>> REPLACE"
        )
        mock_completion = mocker.patch("litellm.completion")

        # Simulate the response being streamed in two parts
        mock_usage_obj = mocker.MagicMock()
        mock_usage_obj.prompt_tokens = 150
        mock_usage_obj.completion_tokens = 50
        mock_usage_obj.total_tokens = 200

        mock_chunk_1 = _create_mock_stream_chunk(llm_diff_response[:60], mocker=mocker)
        mock_chunk_2 = _create_mock_stream_chunk(
            llm_diff_response[60:], mocker=mocker, usage=mock_usage_obj
        )

        mock_stream = mocker.MagicMock()
        mock_stream.__iter__.return_value = iter([mock_chunk_1, mock_chunk_2])
        mock_completion.return_value = mock_stream
        mocker.patch("litellm.completion_cost", return_value=0.002)

        # WHEN `aico prompt` is run (defaulting to conversation mode)
        prompt_text = "Add a name parameter and print it"
        result = runner.invoke(app, ["prompt", prompt_text])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the live display was updated with rendered diff content
        assert "<<<<<<< SEARCH" not in result.stdout
        assert "--- a/code.py" in result.stdout
        assert "+def hello(name: str):" in result.stdout

        # AND the session file still correctly records that mode was `conversation`
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        last_response = session_data["last_response"]
        assert last_response["mode_used"] == "conversation"


def test_drop_multiple_with_one_not_in_context_partially_fails(tmp_path: Path) -> None:
    # GIVEN a session with two files in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        (Path(td) / "file1.py").touch()
        (Path(td) / "file2.py").touch()
        runner.invoke(app, ["add", "file1.py", "file2.py"])

        # WHEN `aico drop` is run with one valid and one invalid file
        result = runner.invoke(app, ["drop", "file1.py", "not_in_context.py"])

        # THEN the command fails with a non-zero exit code
        assert result.exit_code == 1

        # AND it reports the successful removal
        assert "Dropped file from context: file1.py" in result.stdout

        # AND it reports the error for the other file
        assert "Error: File not in context: not_in_context.py" in result.stderr

        # AND the session file is updated to remove the valid file
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert sorted(session_data["context_files"]) == ["file2.py"]


def test_prompt_conversation_mode_with_diff_response_saves_parsed_diff(
    tmp_path: Path, mocker
) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        file_to_edit = Path(td) / "file.py"
        file_to_edit.write_text("old content")
        runner.invoke(app, ["add", "file.py"])

        # AND the LLM API is mocked to return a diff-formatted response
        llm_diff_response = (
            "File: file.py\n"
            "<<<<<<< SEARCH\n"
            "old content\n"
            "=======\n"
            "new content\n"
            ">>>>>>> REPLACE"
        )
        mock_completion = mocker.patch("litellm.completion")
        mock_chunk = _create_mock_stream_chunk(llm_diff_response, mocker=mocker)
        mock_stream = mocker.MagicMock()
        mock_stream.__iter__.return_value = iter([mock_chunk])
        mock_completion.return_value = mock_stream
        mocker.patch("litellm.completion_cost", return_value=None)
        mocker.patch("litellm.token_counter", return_value=1)

        # WHEN `aico prompt` is run (defaulting to conversation)
        result = runner.invoke(app, ["prompt", "make a change"])

        # THEN the command succeeds and still prints the raw output for now
        assert result.exit_code == 0
        assert llm_diff_response in result.stdout

        # AND the session file is updated with BOTH the raw content AND parsed diffs
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        last_response = session_data["last_response"]

        assert last_response["raw_content"] == llm_diff_response
        assert last_response["mode_used"] == "conversation"
        assert "--- a/file.py" in last_response["unified_diff"]
        assert "```diff" in last_response["display_content"]


def test_drop_autocompletion(tmp_path: Path) -> None:
    # GIVEN a session with several files in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # AND a session file is initialized with context files
        runner.invoke(app, ["init"])
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        session_data["context_files"] = [
            "src/main.py",
            "src/utils.py",
            "docs/README.md",
        ]
        session_file.write_text(json.dumps(session_data))

        # WHEN the completion function is called with various partial inputs
        # THEN it returns the correct list of matching files
        assert sorted(complete_files_in_context("src/")) == [
            "src/main.py",
            "src/utils.py",
        ]
        assert complete_files_in_context("docs/") == ["docs/README.md"]
        assert complete_files_in_context("src/main") == ["src/main.py"]
        assert complete_files_in_context("invalid") == []

    # GIVEN a directory with no session file
    with runner.isolated_filesystem():
        # WHEN the completion function is called
        completions = complete_files_in_context("any")
        # THEN it returns an empty list without erroring
        assert completions == []


def test_no_command_shows_help() -> None:
    # GIVEN the app
    # WHEN `aico` is run with no command
    result = runner.invoke(app, [])

    # THEN the command succeeds and shows the help text
    assert result.exit_code == 0
    assert "Usage: root [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert " init" in result.stdout
    assert " add" in result.stdout
    assert " last" in result.stdout
    assert " drop" in result.stdout
    assert " prompt" in result.stdout
