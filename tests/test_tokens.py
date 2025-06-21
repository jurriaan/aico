# pyright: standard

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.main import app
from aico.models import Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME, save_session

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
        session_data = SessionData(
            model="test-model", chat_history=[], context_files=["file1.py"]
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # AND the token counter is mocked
        # It will be called for system prompt, 2x alignment prompts, 1x context file.
        # All will return 10. Max alignment is 10. Total = 10+10+10 = 30.
        mocker.patch("litellm.token_counter", return_value=10)

        # AND litellm provides no cost or context window info
        mocker.patch("litellm.completion_cost", side_effect=ValueError("No cost data"))
        mocker.patch("litellm.get_model_info", return_value={"max_input_tokens": None})

        # WHEN `aico tokens` is run
        result = runner.invoke(app, ["tokens"])

        # THEN the command succeeds and prints the correct token breakdown
        assert result.exit_code == 0
        output = result.stdout
        assert "10" in output and "system prompt" in output
        assert "10" in output and "alignment prompts" in output
        assert "10" in output and "file1.py" in output
        assert "30" in output and "total" in output

        # AND no cost or context window information is displayed
        assert "$" not in output
        assert "max tokens" not in output
        assert "remaining tokens" not in output


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
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # system, align-convo, align-diff, history, file1
        # History is now wrapped in prompt tags, so its token count is slightly higher
        mocker.patch("litellm.token_counter", side_effect=[100, 30, 40, 54, 20])
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
        output = result.stdout
        # Costs based on tokens: 100, 40 (max of 30, 40), 54, 20
        # Total tokens = 100+40+54+20 = 214
        assert "$0.00100" in output  # system prompt (100 tokens)
        assert "$0.00040" in output  # alignment prompts (40 tokens)
        assert "$0.00054" in output  # history (54 tokens)
        assert "$0.00020" in output  # file1 (20 tokens)
        assert "$0.00214" in output and "total" in output
        # Context window
        assert "8,192" in output and "max tokens" in output
        # 8192 - 214 = 7978
        assert "7,978" in output and "remaining tokens" in output
        assert "(97%)" in output


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
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        mocker.patch("litellm.token_counter", side_effect=[100, 30, 40, 54, 20])
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
        # Total tokens = 100 (sys) + 40 (align) + 54 (hist) + 20 (file) = 214
        assert data["model"] == "test-model-json"
        assert len(data["components"]) == 4
        assert data["components"][0]["description"] == "system prompt"
        assert data["components"][0]["tokens"] == 100
        assert data["components"][0]["cost"] == pytest.approx(0.001)
        assert data["components"][1]["description"] == "alignment prompts"
        assert data["components"][1]["tokens"] == 40
        assert data["components"][1]["cost"] == pytest.approx(0.0004)
        assert data["total_tokens"] == 214
        assert data["total_cost"] == pytest.approx(0.00214)
        assert data["max_input_tokens"] == 8192
        assert data["remaining_tokens"] == 7978


def test_tokens_command_hides_zero_remaining_tokens(tmp_path: Path, mocker) -> None:
    """
    Tests that the 'remaining tokens' line is not shown when it is zero,
    but 'max tokens' is still shown.
    """
    # GIVEN a session where the total tokens equals the context window
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        session_data = SessionData(
            model="test-model", context_files=[], chat_history=[]
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # AND litellm is mocked to return a context window size equal to total tokens
        # Calls: system prompt, align-convo, align-diff. All return 100.
        # total tokens = system prompt (100) + alignment (100) = 200
        mocker.patch("litellm.token_counter", return_value=100)
        mocker.patch("litellm.get_model_info", return_value={"max_input_tokens": 200})
        mocker.patch("litellm.completion_cost", return_value=None)

        # WHEN `aico tokens` is run
        result = runner.invoke(app, ["tokens"])

        # THEN the command succeeds
        assert result.exit_code == 0
        # AND 'max tokens' is displayed with the new total
        assert "200" in result.stdout and "max tokens" in result.stdout
        # AND 'remaining tokens' is NOT displayed
        assert "remaining tokens" not in result.stdout
