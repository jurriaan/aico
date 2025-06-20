from pathlib import Path

from typer.testing import CliRunner

from aico.main import app
from aico.models import Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def test_tokens_command(tmp_path: Path, mocker) -> None:
    # GIVEN a session with context files and some history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        (session_dir / "file1.py").write_text("a" * 10)  # Content for file 1
        (session_dir / "file2.py").write_text("b" * 20)  # Content for file 2

        session_data = SessionData(
            model="test-model",
            context_files=["file1.py", "file2.py"],
            chat_history=[
                UserChatMessage(
                    role="user", content="message 1", mode=Mode.RAW, timestamp="ts1"
                ),
                UserChatMessage(
                    role="user", content="message 2", mode=Mode.RAW, timestamp="ts2"
                ),
            ],
            history_start_index=1,  # only message 2 is active
        )
        (session_dir / SESSION_FILE_NAME).write_text(session_data.model_dump_json())

        # AND the token counter is mocked
        mock_token_counter = mocker.patch("litellm.token_counter")

        def side_effect_func(*, model, text=None, messages=None):
            if text:
                if "expert pair programmer" in text:
                    return 100  # System prompt
                elif 'path="file1.py"' in text:
                    return 20  # file1 + wrapper
                elif 'path="file2.py"' in text:
                    return 30  # file2 + wrapper
            elif messages:
                return 50  # Active history
            return 0

        mock_token_counter.side_effect = side_effect_func

        # WHEN `aico tokens` is run
        result = runner.invoke(app, ["tokens"])

        # THEN the command succeeds and prints the correct breakdown
        assert result.exit_code == 0
        assert (
            "Approximate context window usage for test-model, in tokens:"
            in result.stdout
        )
        assert "100" in result.stdout and "system prompt" in result.stdout
        assert "50" in result.stdout and "chat history" in result.stdout
        assert "20" in result.stdout and "file1.py" in result.stdout
        assert "30" in result.stdout and "file2.py" in result.stdout
        assert "200" in result.stdout and "tokens total" in result.stdout
        assert "(use 'aico history' to manage)" in result.stdout
        assert "(use 'aico drop' to remove)" in result.stdout

        # AND the token counter was called for each component
        assert mock_token_counter.call_count == 4
