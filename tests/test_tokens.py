from pathlib import Path

from typer.testing import CliRunner

from aico.main import app
from aico.models import Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def test_tokens_command_shows_token_breakdown_without_cost(
    tmp_path: Path, mocker
) -> None:
    """
    Tests that the tokens command shows a token breakdown but omits cost
    information when litellm does not provide it.
    """
    # GIVEN a session with context files and some history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        (session_dir / "file1.py").write_text("a" * 10)
        (session_dir / "file2.py").write_text("b" * 20)

        session_data = SessionData(
            model="test-model-no-cost",
            context_files=["file1.py", "file2.py"],
            chat_history=[
                UserChatMessage(
                    role="user", content="message 1", mode=Mode.RAW, timestamp="ts1"
                ),
                UserChatMessage(
                    role="user", content="message 2", mode=Mode.RAW, timestamp="ts2"
                ),
            ],
            history_start_index=1,
        )
        (session_dir / SESSION_FILE_NAME).write_text(session_data.model_dump_json())

        # AND the token counter is mocked
        mock_token_counter = mocker.patch("litellm.token_counter")

        def side_effect_func(*, model, text=None, messages=None):
            if text and "expert pair programmer" in text:
                return 100
            if messages:
                return 50
            if text and 'path="file1.py"' in text:
                return 20
            if text and 'path="file2.py"' in text:
                return 30
            return 0

        mock_token_counter.side_effect = side_effect_func

        # AND the completion cost calculator is mocked to return None
        mocker.patch("litellm.completion_cost", return_value=None)

        # WHEN `aico tokens` is run
        result = runner.invoke(app, ["tokens"])

        # THEN the command succeeds and prints the correct token breakdown
        assert result.exit_code == 0
        assert "100" in result.stdout and "system prompt" in result.stdout
        assert "50" in result.stdout and "chat history" in result.stdout
        assert "200" in result.stdout and "total" in result.stdout

        # AND no cost information is displayed
        assert "$" not in result.stdout


def test_tokens_command_shows_cost_breakdown(tmp_path: Path, mocker) -> None:
    """
    Tests that the tokens command shows both token and cost breakdowns when
    cost information is available from litellm.
    """
    # GIVEN a session with context files and history (same as other test)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        (session_dir / "file1.py").write_text("a" * 10)
        (session_dir / "file2.py").write_text("b" * 20)
        session_data = SessionData(
            model="test-model-with-cost",
            context_files=["file1.py", "file2.py"],
            chat_history=[
                UserChatMessage(
                    role="user", content="message 2", mode=Mode.RAW, timestamp="ts2"
                )
            ],
        )
        (session_dir / SESSION_FILE_NAME).write_text(session_data.model_dump_json())

        # AND the token counter is mocked with specific values
        mock_token_counter = mocker.patch("litellm.token_counter")

        def token_side_effect(*, model, text=None, messages=None):
            if text and "expert pair programmer" in text:
                return 100
            if messages:
                return 50
            if text and 'path="file1.py"' in text:
                return 20
            if text and 'path="file2.py"' in text:
                return 30
            return 0

        mock_token_counter.side_effect = token_side_effect

        # AND the completion cost calculator is mocked to return a value
        mock_cost = mocker.patch("litellm.completion_cost")

        def cost_side_effect(*, completion_response):
            # This side effect covers both the initial check and the subsequent calls.
            # It uses a simple cost model for testing: 1/1000th of a cent per token.
            prompt_tokens = completion_response["usage"]["prompt_tokens"]
            return float(prompt_tokens) * 0.00001

        mock_cost.side_effect = cost_side_effect

        # WHEN `aico tokens` is run
        result = runner.invoke(app, ["tokens"])

        # THEN the command succeeds and prints cost information
        assert result.exit_code == 0
        assert (
            "Approximate context window usage for test-model-with-cost, in tokens:"
            in result.stdout
        )
        # Check for costs (tokens * 0.00001)
        assert "$0.00100" in result.stdout  # system prompt (100 tokens)
        assert "$0.00050" in result.stdout  # history (50 tokens)
        assert "$0.00020" in result.stdout  # file1 (20 tokens)
        assert "$0.00030" in result.stdout  # file2 (30 tokens)
        # total tokens = 100+50+20+30 = 200
        assert "$0.00200" in result.stdout and "total" in result.stdout
