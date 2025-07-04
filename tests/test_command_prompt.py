# pyright: standard

from pathlib import Path

import pytest
from pytest_mock import MockerFixture, MockType
from typer.testing import CliRunner

from aico.main import app
from aico.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME, SessionDataAdapter

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


def setup_prompt_test(
    mocker: MockerFixture,
    tmp_path: Path,
    llm_response_content: str,
    context_files: dict[str, str] | None = None,
    usage: object | None = None,
) -> MockType:
    """A helper to handle the common GIVEN steps for prompt command tests."""
    runner.invoke(app, ["init"])

    if context_files:
        for filename, content in context_files.items():
            (tmp_path / filename).write_text(content)
            runner.invoke(app, ["add", filename])

    mock_completion = mocker.patch("litellm.completion")
    mock_chunk = _create_mock_stream_chunk(llm_response_content, mocker=mocker, usage=usage)
    mock_stream = mocker.MagicMock()
    mock_stream.__iter__.return_value = iter([mock_chunk])
    mock_completion.return_value = mock_stream
    mocker.patch("litellm.completion_cost", return_value=0.001)

    return mock_completion


def load_final_session(tmp_path: Path) -> SessionData:
    """Loads and returns the SessionData object from the test's temp directory."""
    session_file = tmp_path / SESSION_FILE_NAME
    return SessionDataAdapter.validate_json(session_file.read_text())


def test_ask_command_injects_alignment(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session with a context file and a mocked LLM
    prompt_text = "Explain this code"
    llm_response = "This is a raw response."
    context_files = {"code.py": "def hello():\n    pass"}
    mock_usage = mocker.MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 20
    mock_usage.total_tokens = 120

    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        mock_completion = setup_prompt_test(
            mocker, Path(td), llm_response, context_files=context_files, usage=mock_usage
        )

        # WHEN `aico ask` is run
        result = runner.invoke(app, ["ask", prompt_text])

        # THEN the command succeeds and prints the raw response
        assert result.exit_code == 0
        assert result.stdout == f"{llm_response}\n"

        # AND the API was called with the correct context and prompt, including alignment
        mock_completion.assert_called_once()
        messages = mock_completion.call_args.kwargs["messages"]
        assert len(messages) == 4
        assert "conversational assistant" in messages[1]["content"]
        assert '<file path="code.py">' in messages[-1]["content"]
        assert f"<prompt>\n{prompt_text}\n</prompt>" in messages[-1]["content"]

        # AND it prints token and cost info to stderr
        assert "Tokens: 100 sent, 20 received." in result.stderr
        assert "Cost: $0.00 message" in result.stderr

        # AND the session history is updated correctly
        final_session = load_final_session(Path(td))
        assert len(final_session.chat_history) == 2
        user_msg, assistant_msg = final_session.chat_history
        assert user_msg.role == "user"
        assert user_msg.content == prompt_text
        assert user_msg.mode == "conversation"
        assert isinstance(assistant_msg, AssistantChatMessage)
        assert assistant_msg.role == "assistant"
        assert assistant_msg.content == llm_response
        assert assistant_msg.mode == "conversation"
        assert assistant_msg.derived is None
        assert assistant_msg.token_usage is not None
        assert assistant_msg.token_usage.prompt_tokens == 100


def test_edit_command_generates_diff(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session with a context file and a mocked LLM returning a diff
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
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_prompt_test(mocker, Path(td), llm_diff_response, context_files={"code.py": "def hello():\n    pass"})

        # WHEN `aico edit` is run
        result = runner.invoke(app, ["edit", "a prompt"])

        # THEN the command succeeds and prints a valid unified diff
        assert result.exit_code == 0
        expected_diff = (
            "--- a/code.py\n"
            "+++ b/code.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def hello():\n"
            "-    pass\n"
            "\\ No newline at end of file\n"
            "+def hello(name: str):\n"
            "+    print(f'Hello, {name}!')\n"
        )
        assert result.stdout == expected_diff

        # AND the session history is updated correctly
        final_session = load_final_session(Path(td))
        user_msg, assistant_msg = final_session.chat_history
        assert user_msg.mode == "diff"
        assert isinstance(assistant_msg, AssistantChatMessage)
        assert assistant_msg.mode == "diff"
        assert assistant_msg.content == llm_diff_response
        assert assistant_msg.derived is not None
        assert assistant_msg.derived.unified_diff == expected_diff


def test_prompt_command_raw_mode_no_alignment(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session and mocked LLM
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        mock_completion = setup_prompt_test(mocker, Path(td), "raw output")

        # WHEN `aico prompt` is run (defaults to raw mode)
        result = runner.invoke(app, ["prompt", "some prompt"])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the API was called without any alignment messages
        messages = mock_completion.call_args.kwargs["messages"]
        assert len(messages) == 2  # system, user
        message_contents = [m["content"] for m in messages]
        assert not any("conversational assistant" in c for c in message_contents)


def test_ask_command_with_diff_response_renders_live_diff(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a TTY-enabled environment and a session with a context file
    mocker.patch("aico.commands.prompt.is_terminal", return_value=True)
    llm_diff_response = (
        "File: code.py\n"
        "<<<<<<< SEARCH\n"
        "def hello(): pass\n"
        "=======\n"
        "def hello(name: str): print(f'Hello, {name}!')\n"
        ">>>>>>> REPLACE"
    )
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_prompt_test(mocker, Path(td), llm_diff_response, context_files={"code.py": "def hello(): pass"})

        # WHEN `aico ask` is run
        result = runner.invoke(app, ["ask", "Add a name parameter and print it"])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the live display was updated with rendered diff content
        assert "<<<<<<< SEARCH" not in result.stdout
        assert "--- a/code.py" in result.stdout
        assert "+def hello(name: str):" in result.stdout

        # AND the session file still correctly records that mode was `conversation`
        final_session = load_final_session(Path(td))
        assert final_session.chat_history[-1].mode == "conversation"


def test_ask_command_with_diff_response_saves_derived_content(tmp_path: Path, mocker) -> None:
    # GIVEN a session and a mocked LLM returning a diff
    llm_diff_response = "File: file.py\n<<<<<<< SEARCH\nold content\n=======\nnew content\n>>>>>>> REPLACE"
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        setup_prompt_test(mocker, Path(td), llm_diff_response, context_files={"file.py": "old content"})

        # WHEN `aico ask` is run
        result = runner.invoke(app, ["ask", "make a change"])

        # THEN the command succeeds and prints the diff response for a non-TTY runner
        assert result.exit_code == 0
        assert result.stdout == f"{llm_diff_response}\n"

        # AND the session file is updated with BOTH the raw content AND parsed diffs
        final_session = load_final_session(Path(td))
        user_msg, assistant_msg = final_session.chat_history
        assert user_msg.content == "make a change"
        assert isinstance(assistant_msg, AssistantChatMessage)
        assert assistant_msg.content == llm_diff_response
        assert assistant_msg.mode == "conversation"
        assert assistant_msg.derived is not None
        assert assistant_msg.derived.unified_diff is not None
        expected_diff = (
            "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old content\n\\ No newline at end of file\n+new content\n"
        )
        assert expected_diff == assistant_msg.derived.unified_diff
        assert f"File: `file.py`\n```diff\n{expected_diff}```\n" == assistant_msg.derived.display_content


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
        mock_completion = setup_prompt_test(mocker, Path(td), "response")

        # WHEN aico prompt is run with a combination of inputs
        invoke_args = ["prompt"]
        if cli_arg:
            invoke_args.append(cli_arg)
        result = runner.invoke(app, invoke_args, input=piped_input)

        # THEN the command succeeds and the LLM was called with the correctly structured prompt
        assert result.exit_code == 0, result.stderr
        user_message_xml = mock_completion.call_args.kwargs["messages"][-1]["content"]

        if expected_piped:
            assert f"<stdin_content>\n{expected_piped}\n</stdin_content>" in user_message_xml
            assert f"<prompt>\n{expected_prompt}\n</prompt>" in user_message_xml
        else:
            assert "<stdin_content>" not in user_message_xml
            assert f"<prompt>\n{expected_prompt}\n</prompt>" in user_message_xml

        # AND the session history was saved correctly
        final_session = load_final_session(Path(td))
        user_msg = final_session.chat_history[0]
        assert isinstance(user_msg, UserChatMessage)
        assert user_msg.content == expected_prompt
        assert user_msg.piped_content == expected_piped


def test_prompt_with_history_reconstructs_piped_content(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session and a mocked LLM
    piped_content = "Here is some code."
    cli_prompt = "Summarize this."
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        mock_completion = setup_prompt_test(mocker, Path(td), "response 1")
        # WHEN the first prompt has piped input and an argument
        runner.invoke(app, ["prompt", cli_prompt], input=piped_content)

        # AND a second prompt is made
        mock_completion.return_value.__iter__.return_value = iter(
            [_create_mock_stream_chunk("response 2", mocker=mocker)]
        )
        runner.invoke(app, ["prompt", "Thanks"])

        # THEN the LLM call for the second prompt contains the reconstructed history
        assert mock_completion.call_count == 2
        messages = mock_completion.call_args.kwargs["messages"]
        historical_user_msg, historical_asst_msg = messages[1:3]
        assert historical_user_msg["role"] == "user"
        expected_reconstructed = (
            f"<stdin_content>\n{piped_content}\n</stdin_content>\n<prompt>\n{cli_prompt}\n</prompt>"
        )
        assert historical_user_msg["content"] == expected_reconstructed
        assert historical_asst_msg["content"] == "response 1"


def test_ask_command_invokes_correct_mode(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mock_invoke_logic = mocker.patch("aico.commands.prompt._invoke_llm_logic")

        # WHEN `aico ask` is run
        result = runner.invoke(app, ["ask", "What does this code do?"])

        # THEN the command succeeds and calls the core logic with conversation mode
        assert result.exit_code == 0
        mock_invoke_logic.assert_called_once()
        assert mock_invoke_logic.call_args[0][2] == Mode.CONVERSATION


def test_edit_command_invokes_correct_mode(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mock_invoke_logic = mocker.patch("aico.commands.prompt._invoke_llm_logic")

        # WHEN `aico edit` is run
        result = runner.invoke(app, ["edit", "Add error handling"])

        # THEN the command succeeds and calls the core logic with diff mode
        assert result.exit_code == 0
        mock_invoke_logic.assert_called_once()
        assert mock_invoke_logic.call_args[0][2] == Mode.DIFF


def test_prompt_defaults_to_raw_mode(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mock_invoke_logic = mocker.patch("aico.commands.prompt._invoke_llm_logic")

        # WHEN `aico prompt` is run without a --mode flag
        result = runner.invoke(app, ["prompt", "Generate a haiku"])

        # THEN the command succeeds and calls the core logic with raw mode
        assert result.exit_code == 0
        mock_invoke_logic.assert_called_once()
        assert mock_invoke_logic.call_args[0][2] == Mode.RAW


def test_prompt_uses_session_default_model_when_not_overridden(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session with a specific default model
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init", "--model", "session/default-model"])
        mock_completion = setup_prompt_test(mocker, Path(td), "response")

        # WHEN `aico prompt` is run without the --model flag
        result = runner.invoke(app, ["prompt", "A prompt"])

        # THEN the command succeeds and the API was called with the session's default model
        assert result.exit_code == 0
        mock_completion.assert_called_once()
        assert mock_completion.call_args.kwargs["model"] == "session/default-model"

        # AND the session file's records show the model used
        final_session = load_final_session(Path(td))
        assistant_msg = final_session.chat_history[1]
        assert isinstance(assistant_msg, AssistantChatMessage)
        assert assistant_msg.model == "session/default-model"


def test_prompt_model_flag_overrides_session_default(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session with a default model and a mocked LLM
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init", "--model", "session/default-model"])
        mock_completion = setup_prompt_test(mocker, Path(td), "response")

        # WHEN `aico prompt` is run with the --model flag
        override_model = "override/specific-model"
        result = runner.invoke(app, ["prompt", "--model", override_model, "A prompt"])

        # THEN the command succeeds and the API was called with the override model
        assert result.exit_code == 0
        mock_completion.assert_called_once()
        assert mock_completion.call_args.kwargs["model"] == override_model

        # AND the session file reflects the correct default and message-specific models
        final_session = load_final_session(Path(td))
        assert final_session.model == "session/default-model"
        assistant_msg = final_session.chat_history[1]
        assert isinstance(assistant_msg, AssistantChatMessage)
        assert assistant_msg.model == override_model


def test_edit_command_with_filesystem_fallback_and_warning(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session and files on disk that are NOT in context
    llm_response = (
        "File: fallback1.py\n<<<<<<< SEARCH\ncontent 1\n=======\nnew content 1\n>>>>>>> REPLACE\n"
        "File: sub/fallback2.py\n<<<<<<< SEARCH\ncontent 2\n=======\nnew content 2\n>>>>>>> REPLACE\n"
    )
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # Initialize an empty session and create files on disk
        setup_prompt_test(mocker, Path(td), llm_response, context_files=None)
        (Path(td) / "fallback1.py").write_text("content 1")
        (Path(td) / "sub").mkdir()
        (Path(td) / "sub/fallback2.py").write_text("content 2\n")

        # WHEN the edit command is run
        result = runner.invoke(app, ["edit", "patch the files"])

        # THEN the command succeeds and the diff is printed to stdout
        assert result.exit_code == 0
        assert "--- a/fallback1.py" in result.stdout
        assert "--- a/sub/fallback2.py" in result.stdout

        # AND two distinct warnings about the fallbacks are printed to stderr
        stderr = result.stderr.replace("\n", "")
        assert "Warnings:" in stderr
        assert "Warning: 'fallback1.py' was not in the session context but was found on disk." in stderr
        assert "Warning: 'sub/fallback2.py' was not in the session context but was found on disk." in stderr


def test_prompt_passthrough_mode_bypasses_context_and_formatting(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an initialized session with files in context
    prompt_text = "some raw prompt"
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        mock_completion = setup_prompt_test(mocker, Path(td), "raw response", context_files={"file.py": "some content"})
        mock_build_contents = mocker.patch("aico.commands.prompt.build_original_file_contents")

        # WHEN `aico prompt --passthrough` is invoked
        result = runner.invoke(app, ["prompt", "--passthrough", prompt_text])

        # THEN the command succeeds and prints the raw response
        assert result.exit_code == 0
        assert result.stdout == "raw response\n"

        # AND the function to load file contents was never called
        mock_build_contents.assert_not_called()

        # AND the LLM was called with a minimal, unformatted message list
        messages = mock_completion.call_args.kwargs["messages"]
        assert len(messages) == 2  # System prompt + User prompt
        assert messages[1]["content"] == prompt_text  # Content is raw, no XML

        # AND the session history correctly records the passthrough state
        final_session = load_final_session(Path(td))
        user_msg = final_session.chat_history[0]
        assert isinstance(user_msg, UserChatMessage)
        assert user_msg.passthrough is True
