# pyright: standard

import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture, MockType
from typer.testing import CliRunner

from aico.main import app
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def _create_mock_stream_chunk(content: str | None, mocker: MockerFixture, usage: object | None = None) -> object:
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
        mock_chunk_2 = _create_mock_stream_chunk("raw response.", mocker=mocker, usage=mock_usage_obj)

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
        assert user_msg["piped_content"] is None
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

        # last_response is gone, we check the last history item
        last_asst_msg = session_data["chat_history"][-1]
        assert last_asst_msg["content"] == "This is a raw response."
        # For a purely conversational response, derived content should be None
        assert last_asst_msg["derived"] is None

        # AND the new metadata is present on the message itself
        assert last_asst_msg["model"] == "openrouter/google/gemini-2.5-pro"
        assert last_asst_msg["timestamp"] is not None
        assert last_asst_msg["duration_ms"] > -1
        assert last_asst_msg["token_usage"]["prompt_tokens"] == 100
        assert last_asst_msg["cost"] is not None


def test_prompt_diff_mode(tmp_path: Path, mocker) -> None:
    # GIVEN a session with a context file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        code_file = Path(td) / "code.py"
        code_file.write_text("def hello():\n    pass")
        runner.invoke(app, ["add", "code.py"])

        # AND the LLM is mocked to stream a diff response
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
        mock_chunk = _create_mock_stream_chunk(llm_diff_response, mocker=mocker)
        mock_stream = mocker.MagicMock()
        mock_stream.__iter__.return_value = iter([mock_chunk])
        mock_completion.return_value = mock_stream
        mocker.patch("litellm.completion_cost", return_value=None)
        mocker.patch("litellm.token_counter", return_value=1)

        # WHEN `aico prompt --mode diff` is run
        result = runner.invoke(app, ["prompt", "--mode", "diff", "a prompt"])

        # THEN the command succeeds and prints a valid unified diff fragment.
        # Detailed diff content tests belong in `test_diffing.py`.
        assert result.exit_code == 0
        assert "--- a/code.py" in result.stdout
        assert "+def hello(name: str):" in result.stdout

        # AND the session history is updated correctly
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        last_user_msg = session_data["chat_history"][-2]
        assert last_user_msg["mode"] == "diff"

        last_asst_msg = session_data["chat_history"][-1]
        assert last_asst_msg["mode"] == "diff"
        assert last_asst_msg["content"] == llm_diff_response
        assert last_asst_msg["derived"]["unified_diff"] is not None
        assert last_asst_msg["derived"]["display_content"] is not None


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


def test_prompt_conversation_mode_with_diff_response_renders_live_diff(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a TTY-enabled environment and a session with a context file
    mocker.patch("aico.commands.prompt.is_terminal", return_value=True)

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
        mock_chunk_2 = _create_mock_stream_chunk(llm_diff_response[60:], mocker=mocker, usage=mock_usage_obj)

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
        last_asst_msg = session_data["chat_history"][-1]
        assert last_asst_msg["mode"] == "conversation"


def test_prompt_conversation_mode_with_diff_response_saves_derived_content(tmp_path: Path, mocker) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        file_to_edit = Path(td) / "file.py"
        file_to_edit.write_text("old content")
        runner.invoke(app, ["add", "file.py"])

        # AND the LLM API is mocked to return a diff-formatted response
        llm_diff_response = "File: file.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE"
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

        # AND check the user message in history
        user_msg = session_data["chat_history"][0]
        assert user_msg["content"] == "make a change"
        assert user_msg["piped_content"] is None

        last_asst_msg = session_data["chat_history"][-1]

        assert last_asst_msg["content"] == llm_diff_response
        assert last_asst_msg["mode"] == "conversation"
        assert last_asst_msg["derived"] is not None
        assert "--- a/file.py" in last_asst_msg["derived"]["unified_diff"]
        assert "```diff" in last_asst_msg["derived"]["display_content"]


# --- Tests for stdin piping ---


def test_prompt_fails_with_no_input(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch("aico.commands.prompt.is_input_terminal", return_value=True)
        runner.invoke(app, ["init"])

        # AND the interactive prompt is mocked to return an empty string (user pressing Enter)
        mocker.patch("aico.commands.prompt.Prompt.ask", return_value="")

        # WHEN `aico prompt` is run with no argument and no piped input
        result = runner.invoke(app, ["prompt"])

        # THEN the command fails with an error
        assert result.exit_code == 1
        assert "Error: Prompt is required." in result.stderr


@pytest.mark.parametrize(
    "cli_arg, piped_input, expected_prompt, expected_piped",
    [
        ("cli arg", None, "cli arg", None),
        (None, "pipe in", "pipe in", None),
        ("cli arg", "pipe in", "cli arg", "pipe in"),
    ],
    ids=["cli_arg_only", "piped_only", "both_cli_and_piped"],
)
def test_prompt_input_scenarios(
    cli_arg: str | None,
    piped_input: str | None,
    expected_prompt: str,
    expected_piped: str | None,
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    # GIVEN an initialized session and mocked LLM
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        mock_completion = mocker.patch("litellm.completion")
        mock_chunk = _create_mock_stream_chunk("response", mocker=mocker)
        mock_stream = mocker.MagicMock()
        mock_stream.__iter__.return_value = iter([mock_chunk])
        mock_completion.return_value = mock_stream
        mocker.patch("litellm.token_counter", return_value=1)
        mocker.patch("litellm.completion_cost", return_value=None)

        # WHEN aico prompt is run with a combination of inputs
        invoke_args = ["prompt"]
        if cli_arg:
            invoke_args.append(cli_arg)
        result = runner.invoke(app, invoke_args, input=piped_input)

        # THEN the command succeeds
        assert result.exit_code == 0, result.stderr

        # AND the LLM was called with the correctly structured user prompt
        messages = mock_completion.call_args.kwargs["messages"]
        user_message_xml = messages[-1]["content"]

        if expected_piped:
            assert f"<stdin_content>\n{expected_piped}\n</stdin_content>" in user_message_xml
            assert f"<prompt>\n{expected_prompt}\n</prompt>" in user_message_xml
        else:
            assert "<stdin_content>" not in user_message_xml
            assert f"<prompt>\n{expected_prompt}\n</prompt>" in user_message_xml

        # AND the session history was saved correctly
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        user_msg = session_data["chat_history"][0]
        assert user_msg["content"] == expected_prompt
        assert user_msg["piped_content"] == expected_piped


def test_prompt_with_history_reconstructs_piped_content(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])
        mock_completion = mocker.patch("litellm.completion")
        mocker.patch("litellm.token_counter", return_value=1)
        mocker.patch("litellm.completion_cost", return_value=None)

        # WHEN the first prompt has piped input and an argument
        mock_chunk_1 = _create_mock_stream_chunk("response 1", mocker=mocker)
        mock_stream_1 = mocker.MagicMock()
        mock_stream_1.__iter__.return_value = iter([mock_chunk_1])
        mock_completion.return_value = mock_stream_1

        piped_content = "Here is some code."
        cli_prompt = "Summarize this."
        runner.invoke(app, ["prompt", cli_prompt], input=piped_content)

        # AND a second prompt is made
        mock_chunk_2 = _create_mock_stream_chunk("response 2", mocker=mocker)
        mock_stream_2 = mocker.MagicMock()
        mock_stream_2.__iter__.return_value = iter([mock_chunk_2])
        mock_completion.return_value = mock_stream_2

        runner.invoke(app, ["prompt", "Thanks"])

        # THEN the LLM call for the second prompt contains the reconstructed history
        assert mock_completion.call_count == 2
        messages = mock_completion.call_args.kwargs["messages"]

        # Expected messages: [system, user1_reconstructed, asst1, align_user, align_asst, user2]
        historical_user_msg = messages[1]
        assert historical_user_msg["role"] == "user"

        expected_reconstructed_content = (
            f"<stdin_content>\n{piped_content}\n</stdin_content>\n<prompt>\n{cli_prompt}\n</prompt>"
        )
        assert historical_user_msg["content"] == expected_reconstructed_content

        historical_asst_msg = messages[2]
        assert historical_asst_msg["role"] == "assistant"
        assert historical_asst_msg["content"] == "response 1"

        current_user_msg = messages[-1]
        assert current_user_msg["role"] == "user"
        # The current prompt has file context as well, so we check for `in`
        assert "<prompt>\nThanks\n</prompt>" in current_user_msg["content"]


def test_prompt_uses_session_default_model_when_not_overridden(tmp_path: Path, mocker: MockerFixture) -> None:
    """Verifies `aico prompt` uses the session's default model when no override is provided."""
    # GIVEN an initialized session with a specific default model
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # Use 'init' to create the session with a non-default model name
        runner.invoke(app, ["init", "--model", "session/default-model"])

        # AND the LLM API is mocked
        mock_completion = mocker.patch("litellm.completion")
        mock_chunk = _create_mock_stream_chunk("response", mocker=mocker)
        mock_stream = mocker.MagicMock()
        mock_stream.__iter__.return_value = iter([mock_chunk])
        mock_completion.return_value = mock_stream
        mocker.patch("litellm.completion_cost", return_value=None)

        # WHEN `aico prompt` is run without the --model flag
        result = runner.invoke(app, ["prompt", "A prompt"])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the API was called with the session's default model
        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["model"] == "session/default-model"

        # AND the session file's records show the model used
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        assert session_data["chat_history"][1]["model"] == "session/default-model"


def _setup_session_with_mocked_prompt(
    tmp_path: Path, mocker: MockerFixture, llm_response: str, context_files: dict[str, str] | None = None
) -> tuple[Path, MockType]:
    """Helper to set up a test session with a mocked LLM response."""
    runner.invoke(app, ["init"])
    session_file = tmp_path / SESSION_FILE_NAME

    if context_files:
        for file_path, content in context_files.items():
            full_path = tmp_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            runner.invoke(app, ["add", file_path])

    mock_completion = mocker.patch("litellm.completion")
    mock_chunk = _create_mock_stream_chunk(llm_response, mocker=mocker)
    mock_stream = mocker.MagicMock()
    mock_stream.__iter__.return_value = iter([mock_chunk])
    mock_completion.return_value = mock_stream
    mocker.patch("litellm.completion_cost", return_value=None)
    mocker.patch("litellm.token_counter", return_value=1)

    return session_file, mock_completion


def test_prompt_model_flag_overrides_session_default(tmp_path: Path, mocker: MockerFixture) -> None:
    """Verifies the --model flag on `aico prompt` overrides the session default for one call."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file, mock_completion = _setup_session_with_mocked_prompt(Path(td), mocker, "response")
        session_data = json.loads(session_file.read_text())
        session_data["model"] = "session/default-model"
        session_file.write_text(json.dumps(session_data))

        override_model = "override/specific-model"
        result = runner.invoke(app, ["prompt", "--model", override_model, "A prompt"])

        assert result.exit_code == 0

        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["model"] == override_model

        session_data = json.loads(session_file.read_text())
        assert session_data["model"] == "session/default-model"
        assert session_data["chat_history"][1]["model"] == override_model


def test_prompt_with_filesystem_fallback_and_warning(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session, and two files that exist on disk but are NOT in the session context.
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        llm_response_content = (
            "File: fallback1.py\n"
            "<<<<<<< SEARCH\n"
            "content 1\n"
            "=======\n"
            "new content 1\n"
            ">>>>>>> REPLACE\n"
            "File: sub/fallback2.py\n"
            "<<<<<<< SEARCH\n"
            "content 2\n"
            "=======\n"
            "new content 2\n"
            ">>>>>>> REPLACE\n"
        )
        # This helper initializes a session with an empty context and mocks the LLM call
        _, _ = _setup_session_with_mocked_prompt(Path(td), mocker, llm_response_content, context_files=None)

        # Create files on disk inside the isolated directory but do not add them to context
        (Path(td) / "fallback1.py").write_text("content 1")
        (Path(td) / "sub").mkdir()
        (Path(td) / "sub/fallback2.py").write_text("content 2\n")

        # WHEN the prompt command is run
        result = runner.invoke(app, ["prompt", "--mode", "diff", "patch the files"])

        # THEN the command succeeds and the diff is printed to stdout
        assert result.exit_code == 0
        # The exact format of the diff is tested in `test_diffing.py`. Here we just check for presence.
        assert "--- a/fallback1.py" in result.stdout
        assert "--- a/sub/fallback2.py" in result.stdout

        # AND two distinct warnings about the fallbacks are printed to stderr
        stderr = result.stderr.replace("\n", "")
        assert "Warnings:" in stderr
        assert "Warning: 'fallback1.py' was not in the session context but was found on disk." in stderr
        assert "Warning: 'sub/fallback2.py' was not in the session context but was found on disk." in stderr
        assert "Consider adding it to the session." in stderr


def test_prompt_passthrough_mode_bypasses_context_and_formatting(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session with files in context and a mocked LLM
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # Use the helper to set up a session with a context file
        context_files = {"file.py": "some content"}
        _, mock_completion = _setup_session_with_mocked_prompt(
            Path(td), mocker, "raw response", context_files=context_files
        )

        # AND a mock for the function that loads file contents
        mock_build_contents = mocker.patch("aico.utils.build_original_file_contents", return_value=context_files)

        # WHEN `aico prompt --passthrough` is invoked
        prompt_text = "some raw prompt"
        result = runner.invoke(app, ["prompt", "--passthrough", prompt_text])

        # THEN the command succeeds
        assert result.exit_code == 0
        assert result.stdout == "raw response\n"

        # AND the function to load file contents was never called, proving context was skipped
        mock_build_contents.assert_not_called()

        # AND the LLM was called with a minimal, unformatted message list
        mock_completion.assert_called_once()
        messages = mock_completion.call_args.kwargs["messages"]
        assert len(messages) == 2  # System prompt + User prompt
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == prompt_text  # Content is raw, no XML

        # AND the session history correctly records the passthrough state
        session_file = Path(td) / SESSION_FILE_NAME
        session_data = json.loads(session_file.read_text())
        user_msg = session_data["chat_history"][0]
        assert user_msg["passthrough"] is True
