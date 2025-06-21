import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.main import app
from aico.models import Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def test_tokens_command_no_cost_or_window_info(tmp_path: Path, mocker) -> None:
    """
    Tests that the tokens command shows a token breakdown but omits cost
    and context window info when litellm does not provide it.
    """
    # GIVEN a session with context files and some history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        (session_dir / "file1.py").write_text("a" * 10)
        session_data = SessionData(model="test-model", context_files=["file1.py"])
        (session_dir / SESSION_FILE_NAME).write_text(session_data.model_dump_json())

        # AND the token counter is mocked
        mocker.patch("litellm.token_counter", return_value=10)

        # AND litellm provides no cost or context window info
        mocker.patch("litellm.completion_cost", return_value=None)
        mocker.patch("litellm.get_model_info", return_value={"max_input_tokens": None})

        # WHEN `aico tokens` is run
        result = runner.invoke(app, ["tokens"])

        # THEN the command succeeds and prints the correct token breakdown
        assert result.exit_code == 0
        assert "10" in result.stdout and "system prompt" in result.stdout
        assert "20" in result.stdout and "total" in result.stdout

        # AND no cost or context window information is displayed
        assert "$" not in result.stdout
        assert "max tokens" not in result.stdout
        assert "remaining tokens" not in result.stdout


def test_tokens_command_shows_full_breakdown(tmp_path: Path, mocker) -> None:
    """
    Tests that the tokens command shows tokens, costs, and context window
    info when all data is available from litellm.
    """
    # GIVEN a session with context files and history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        (session_dir / "file1.py").write_text("a" * 10)
        session_data = SessionData(
            model="test-model-with-cost",
            context_files=["file1.py"],
            chat_history=[
                UserChatMessage(
                    role="user",
                    content="message 2",
                    mode=Mode.CONVERSATION,
                    timestamp="ts2",
                )
            ],
        )
        (session_dir / SESSION_FILE_NAME).write_text(session_data.model_dump_json())

        mocker.patch("litellm.token_counter", side_effect=[100, 50, 20])
        mocker.patch(
            "litellm.completion_cost",
            side_effect=lambda completion_response: float(
                completion_response["usage"]["prompt_tokens"]
            )
            * 0.00001,
        )
        mocker.patch("litellm.get_model_info", return_value={"max_input_tokens": 8192})

        # WHEN `aico tokens` is run
        result = runner.invoke(app, ["tokens"])

        # THEN the command succeeds and prints all information
        assert result.exit_code == 0
        # Costs
        assert "$0.00100" in result.stdout  # system prompt
        assert "$0.00050" in result.stdout  # history
        assert "$0.00020" in result.stdout  # file1
        assert "$0.00170" in result.stdout and "total" in result.stdout
        # Context window
        assert "8,192" in result.stdout and "max tokens" in result.stdout
        # 8192 - (100+50+20) = 8022
        assert "8,022" in result.stdout and "remaining tokens" in result.stdout
        assert "(98%)" in result.stdout


def test_tokens_command_json_output(tmp_path: Path, mocker) -> None:
    """
    Tests that the --json flag produces a comprehensive JSON report.
    """
    # GIVEN a session and mocks for all data sources
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        (session_dir / "file1.py").write_text("a" * 10)
        session_data = SessionData(
            model="test-model-json",
            context_files=["file1.py"],
            chat_history=[
                UserChatMessage(
                    role="user",
                    content="message 2",
                    mode=Mode.CONVERSATION,
                    timestamp="ts2",
                )
            ],
        )
        (session_dir / SESSION_FILE_NAME).write_text(session_data.model_dump_json())

        mocker.patch("litellm.token_counter", side_effect=[100, 50, 20])
        mocker.patch(
            "litellm.completion_cost",
            side_effect=lambda completion_response: float(
                completion_response["usage"]["prompt_tokens"]
            )
            * 0.00001,
        )
        mocker.patch("litellm.get_model_info", return_value={"max_input_tokens": 8192})

        # WHEN `aico tokens --json` is run
        result = runner.invoke(app, ["tokens", "--json"])

        # THEN the command succeeds and the output is valid JSON
        assert result.exit_code == 0
        data = json.loads(result.stdout)

        # AND the JSON data matches the expected TokenReport structure and values
        assert data["model"] == "test-model-json"
        assert len(data["components"]) == 3
        assert data["components"][0]["description"] == "system prompt"
        assert data["components"][0]["tokens"] == 100
        assert data["components"][0]["cost"] == pytest.approx(0.001)
        assert data["total_tokens"] == 170
        assert data["total_cost"] == pytest.approx(0.0017)
        assert data["max_input_tokens"] == 8192
        assert data["remaining_tokens"] == 8022


def test_tokens_command_hides_zero_remaining_tokens(tmp_path: Path, mocker) -> None:
    """
    Tests that the 'remaining tokens' line is not shown when it is zero,
    but 'max tokens' is still shown.
    """
    # GIVEN a session where the total tokens equals the context window
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        session_data = SessionData(
            model="test-model",
        )
        (session_dir / SESSION_FILE_NAME).write_text(session_data.model_dump_json())

        # AND litellm is mocked to return a context window size equal to total tokens
        # total tokens = system prompt (100)
        mocker.patch("litellm.token_counter", return_value=100)
        mocker.patch("litellm.get_model_info", return_value={"max_input_tokens": 100})
        mocker.patch("litellm.completion_cost", return_value=None)

        # WHEN `aico tokens` is run
        result = runner.invoke(app, ["tokens"])

        # THEN the command succeeds
        assert result.exit_code == 0
        # AND 'max tokens' is displayed
        assert "100" in result.stdout and "max tokens" in result.stdout
        # AND 'remaining tokens' is NOT displayed
        assert "remaining tokens" not in result.stdout
