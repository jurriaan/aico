# pyright: standard

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.lib.models import (
    AssistantChatMessage,
    DerivedContent,
    Mode,
    SessionData,
    UserChatMessage,
)
from aico.lib.session import SESSION_FILE_NAME, save_session
from aico.main import app
from tests.test_command_undo import load_session_data

runner = CliRunner()


@pytest.fixture
def session_with_context_file(tmp_path: Path) -> Path:
    """Creates a session file in a temporary directory with one file in context."""
    session_dir = tmp_path
    os.chdir(session_dir)
    (session_dir / "code.py").write_text("def hello(): pass")
    session_file = session_dir / SESSION_FILE_NAME
    session_data = SessionData(
        model="test-model",
        context_files=["code.py"],
        chat_history=[],
    )
    save_session(session_file, session_data)
    return session_file


def mock_editor(new_content: str, return_code: int = 0) -> MagicMock:
    """Creates a mock side effect for subprocess.run to simulate an editor."""

    def _side_effect(cmd_parts: list[str], check: bool) -> subprocess.CompletedProcess[str]:  # pyright: ignore[reportUnusedParameter]
        temp_file_path = Path(cmd_parts[-1])
        if return_code == 0:
            temp_file_path.write_text(new_content)
        return subprocess.CompletedProcess(args=cmd_parts, returncode=return_code, stdout="", stderr="")

    return MagicMock(side_effect=_side_effect)


def test_edit_prompt(session_with_two_pairs: Path, mocker: MockerFixture) -> None:  # noqa F811 module-private
    # GIVEN a session, a mocked editor, and an environment where EDITOR is not set
    mocker.patch.dict(os.environ).pop("EDITOR", None)

    session_file = session_with_two_pairs
    mock_run = mocker.patch("subprocess.run", new=mock_editor("Updated prompt content"))

    # WHEN `aico edit --prompt` is run on the first pair (index 0)
    result = runner.invoke(app, ["edit", "0", "--prompt"])

    # THEN the command succeeds and reports the update
    assert result.exit_code == 0, result.stderr
    assert "Updated prompt for message pair 0." in result.stdout

    # AND the session file is updated with the new prompt content
    final_session = load_session_data(session_file)
    assert final_session.chat_history[0].content == "Updated prompt content"
    assert final_session.chat_history[1].content == "assistant response 0"  # Unchanged

    # AND the editor was called correctly
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0][0] == "vi"  # Default editor


def test_edit_response_and_invalidate_derived_content(session_with_two_pairs: Path, mocker: MockerFixture) -> None:  # noqa F811 module-private
    # GIVEN a session where the last response has derived content
    session_file = session_with_two_pairs
    session_data = load_session_data(session_file)
    from dataclasses import replace

    last_response = session_data.chat_history[-1]
    last_response_with_derived = replace(
        last_response, derived=DerivedContent(unified_diff="diff", display_content="display")
    )
    session_data.chat_history[-1] = last_response_with_derived
    save_session(session_file, session_data)

    # AND a mocked editor that will succeed
    mock_run = mocker.patch("subprocess.run", new=mock_editor("Updated response content"))

    # WHEN `aico edit` is run with default arguments (last response)
    result = runner.invoke(app, ["edit"])

    # THEN the command succeeds
    assert result.exit_code == 0
    assert "Updated response for message pair 1." in result.stdout

    # AND the response content is updated
    final_session = load_session_data(session_file)
    final_response = final_session.chat_history[-1]
    assert final_response.content == "Updated response content"

    # AND the derived content is recomputed but is None because the new content is just conversational
    assert isinstance(final_response, AssistantChatMessage)
    assert final_response.derived is None

    mock_run.assert_called_once()


def test_edit_with_custom_editor(session_with_two_pairs: Path, mocker: MockerFixture) -> None:  # noqa F811 module-private
    # GIVEN a mocked editor and a custom EDITOR env var
    _ = session_with_two_pairs
    mock_run = mocker.patch("subprocess.run", new=mock_editor("new content"))
    mocker.patch.dict(os.environ, {"EDITOR": "nvim -f"})

    # WHEN `aico edit` is run
    result = runner.invoke(app, ["edit"])

    # THEN the command succeeds
    assert result.exit_code == 0

    # AND the custom editor command was used
    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "nvim"
    assert called_cmd[1] == "-f"


def test_edit_aborts_if_no_changes(session_with_two_pairs: Path, mocker: MockerFixture) -> None:  # noqa F811 module-private
    # GIVEN a mocked editor that makes no changes
    session_file = session_with_two_pairs
    original_content = load_session_data(session_file).chat_history[-1].content
    mocker.patch("subprocess.run", new=mock_editor(original_content))

    # WHEN `aico edit` is run
    result = runner.invoke(app, ["edit"])

    # THEN the command succeeds but reports no changes
    assert result.exit_code == 0
    assert "No changes detected. Aborting." in result.stdout


def test_edit_aborts_on_editor_failure(session_with_two_pairs: Path, mocker: MockerFixture) -> None:  # noqa F811 module-private
    # GIVEN a mocked editor that returns a non-zero exit code
    _ = session_with_two_pairs
    mocker.patch("subprocess.run", new=mock_editor("irrelevant", return_code=1))

    # WHEN `aico edit` is run
    result = runner.invoke(app, ["edit"])

    # THEN the command fails and reports the editor failure
    assert result.exit_code == 1
    assert "Editor closed with non-zero exit code. Aborting." in result.stderr


def test_edit_fails_on_bad_index(session_with_two_pairs: Path) -> None:  # noqa F811 module-private
    # GIVEN a session
    # WHEN `aico edit` is called with an out-of-bounds index
    result = runner.invoke(app, ["edit", "99"])

    # THEN it fails with a clear error
    assert result.exit_code == 1
    assert "Error: Pair at index 99 not found." in result.stderr


def test_edit_fails_if_editor_not_found(session_with_two_pairs: Path, mocker: MockerFixture) -> None:  # noqa F811 module-private
    # GIVEN a mocked subprocess.run that raises FileNotFoundError
    mocker.patch("subprocess.run", side_effect=FileNotFoundError)

    # WHEN `aico edit` is run
    result = runner.invoke(app, ["edit"])

    # THEN the command fails with a helpful error message
    assert result.exit_code == 1
    assert "Error: Editor command not found" in result.stderr
    assert "Please set the $EDITOR environment variable." in result.stderr


def test_edit_response_recomputes_derived_content_on_change(
    session_with_context_file: Path, mocker: MockerFixture
) -> None:
    # GIVEN a session with a file in context and one message pair
    session_file = session_with_context_file
    session_data = load_session_data(session_file)

    user_msg = UserChatMessage(role="user", content="prompt", mode=Mode.CONVERSATION, timestamp="ts")
    assistant_msg = AssistantChatMessage(
        role="assistant",
        content="Initial conversational response.",
        mode=Mode.CONVERSATION,
        timestamp="ts",
        model="test-model",
        duration_ms=100,
    )
    session_data.chat_history = [user_msg, assistant_msg]
    save_session(session_file, session_data)

    # AND a mocked editor that will provide a valid patch
    new_patch_content = (
        "File: code.py\n<<<<<<< SEARCH\ndef hello(): pass\n=======\ndef greeting(): print('hello')\n>>>>>>> REPLACE"
    )
    mock_run = mocker.patch("subprocess.run", new=mock_editor(new_patch_content))

    # WHEN `aico edit` is run with default arguments (last response)
    result = runner.invoke(app, ["edit"])

    # THEN the command succeeds
    assert result.exit_code == 0, result.stderr
    assert "Updated response for message pair 0." in result.stdout

    # AND the response content is updated
    final_session = load_session_data(session_file)
    final_response = final_session.chat_history[-1]
    assert isinstance(final_response, AssistantChatMessage)
    assert final_response.content == new_patch_content

    # AND the derived content is recomputed and contains the new diff
    assert final_response.derived is not None
    assert isinstance(final_response.derived, DerivedContent)

    expected_diff = (
        "--- a/code.py\n"
        "+++ b/code.py\n"
        "@@ -1 +1 @@\n"
        "-def hello(): pass\n"
        "\\ No newline at end of file\n"
        "+def greeting(): print('hello')\n"
    )
    assert final_response.derived.unified_diff == expected_diff

    # AND the display content is also correct
    expected_display_items = [
        {"type": "markdown", "content": "File: `code.py`\n"},
        {"type": "diff", "content": expected_diff},
    ]
    assert final_response.derived.display_content == expected_display_items
    mock_run.assert_called_once()
