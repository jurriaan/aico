# pyright: standard

from pathlib import Path

from typer.testing import CliRunner

from aico.main import app
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from aico.utils import SESSION_FILE_NAME, save_session

runner = CliRunner()


def test_status_full_breakdown(tmp_path: Path, mocker) -> None:
    """
    Tests that the status command shows tokens, costs, and context window
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
                    content="message 1",
                    mode=Mode.CONVERSATION,
                    timestamp="ts1",
                ),
                AssistantChatMessage(
                    role="assistant",
                    content="response 1",
                    mode=Mode.CONVERSATION,
                    timestamp="ts1",
                    model="m",
                    duration_ms=1,
                ),
            ],
            history_start_index=0,
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # Mocks for litellm. The status command will get tokens for:
        # system prompt, alignment prompts (x2), chat history, and context files (x1)
        mocker.patch("litellm.token_counter", side_effect=[100, 30, 40, 50, 20])
        mocker.patch(
            "litellm.completion_cost",
            side_effect=lambda completion_response: float(completion_response["usage"]["prompt_tokens"]) * 0.0001,
        )
        mocker.patch("litellm.get_model_info", return_value={"max_input_tokens": 8192, "input_cost_per_token": 0.0001})

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and prints all information
        assert result.exit_code == 0
        output = result.stdout

        # Check titles and headers
        assert "Status for model" in output
        assert "test-model-with-cost" in output
        assert "Tokens" in output and "Cost" in output and "Component" in output

        # Check component costs and tokens
        # Tokens: 100(sys) + 40(max of 30,40 for align) + 50(hist) + 20(file) = 210
        assert "100" in output and "system prompt" in output and "$0.01000" in output
        assert "40" in output and "alignment prompts" in output and "$0.00400" in output
        assert "50" in output and "chat history" in output and "$0.00500" in output
        assert "20" in output and "file1.py" in output and "$0.0020" in output

        # Check history summary
        assert "Active window: 1 pair (ID 0), 1 sent." in output

        # Check file group header
        assert "Context Files (1)" in output

        # Check total
        assert "210" in output and "Total" in output and "$0.0210" in output

        # Check context window
        assert "Context Window" in output
        assert "8,192" in output
        assert "97% remaining" in output


def test_status_handles_unknown_model(tmp_path: Path, mocker) -> None:
    """
    Tests that the status command handles cases where model info (cost, context) is unavailable.
    """
    # GIVEN a session with an unknown model
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        session_data = SessionData(model="unknown-model", context_files=[], chat_history=[])
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        mocker.patch("litellm.token_counter", return_value=10)
        mocker.patch("litellm.get_model_info", return_value=None)
        mocker.patch("litellm.completion_cost", side_effect=Exception("No cost info"))

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and prints the token breakdown
        assert result.exit_code == 0
        output = result.stdout
        assert "10" in output and "system prompt" in output
        # Total tokens: 10(sys) + 10(align) = 20
        assert "20" in output and "Total" in output

        # AND no cost or context window information is displayed
        assert "Cost" in output  # The column header still exists
        assert "$" not in output
        assert "Context Window" not in output


def test_status_omits_excluded_messages(tmp_path: Path, mocker) -> None:
    """
    Tests that `aico status` correctly excludes messages marked with is_excluded=True
    from its token calculation and updates the summary text.
    """
    # GIVEN a session with a mix of active and excluded history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        history = [
            UserChatMessage(role="user", content="active message", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(
                role="assistant",
                content="active resp",
                mode=Mode.CONVERSATION,
                timestamp="t2",
                model="m",
                duration_ms=1,
            ),
            UserChatMessage(
                role="user", content="excluded message", mode=Mode.CONVERSATION, timestamp="t3", is_excluded=True
            ),
            AssistantChatMessage(
                role="assistant",
                content="excluded resp",
                mode=Mode.CONVERSATION,
                timestamp="t3",
                model="m",
                duration_ms=1,
                is_excluded=True,
            ),
        ]
        session_data = SessionData(model="test-model", context_files=[], chat_history=history)
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # AND the token counter is mocked
        mock_token_counter = mocker.patch("litellm.token_counter")
        # system, align-convo, align-diff, chat history for active messages
        mock_token_counter.side_effect = [100, 50, 40, 20]
        mocker.patch("litellm.completion_cost", return_value=None)
        mocker.patch("litellm.get_model_info", return_value={"max_input_tokens": 1000})

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds
        assert result.exit_code == 0
        output = result.stdout

        # AND the "chat history" component should have a count of 20
        assert "chat history" in output
        assert "20" in output

        # AND the total should reflect only the active messages
        # The max alignment prompt tokens will be 50. Total = 100(sys) + 50(align) + 20(hist) = 170.
        assert "170" in output and "Total" in output

        # AND the history summary text correctly reports the exclusion
        assert "Active window: 2 pairs (IDs 0-1), 1 sent (1 excluded" in output

        # AND the reconstructed messages passed to the token counter should not contain the excluded message
        # system, align1, align2, history
        history_call = mock_token_counter.call_args_list[3]
        messages_arg = history_call.kwargs["messages"]
        assert len(messages_arg) == 2
        assert "active message" in messages_arg[0]["content"]
        assert "active resp" in messages_arg[1]["content"]


def test_status_history_summary_logic(tmp_path: Path, mocker) -> None:
    # GIVEN a session with 3 pairs, start index at 2 (msg index), one pair excluded
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        history = [
            UserChatMessage(role="user", content="msg 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(
                role="assistant", content="resp 0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1
            ),
            UserChatMessage(role="user", content="msg 1", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(
                role="assistant", content="resp 1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1
            ),
            UserChatMessage(role="user", content="msg 2", mode=Mode.CONVERSATION, timestamp="t2", is_excluded=True),
            AssistantChatMessage(
                role="assistant",
                content="resp 2",
                mode=Mode.CONVERSATION,
                timestamp="t2",
                model="m",
                duration_ms=1,
                is_excluded=True,
            ),
        ]
        # Active context starts at Pair 1 (user message index 2)
        session_data = SessionData(
            model="test-model",
            chat_history=history,
            context_files=[],
            history_start_index=2,
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)
        mocker.patch("litellm.token_counter", return_value=10)
        mocker.patch("litellm.get_model_info", return_value=None)

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and shows the correct summary
        assert result.exit_code == 0
        assert "Active window: 2 pairs (IDs 1-2), 1 sent (1 excluded" in result.stdout


def test_status_handles_dangling_messages(tmp_path: Path, mocker) -> None:
    # GIVEN a session with a dangling user message
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        history: list[ChatMessageHistoryItem] = [
            UserChatMessage(role="user", content="dangling", mode=Mode.CONVERSATION, timestamp="t1")
        ]
        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        save_session(session_dir / SESSION_FILE_NAME, session_data)
        mocker.patch("litellm.token_counter", return_value=10)
        mocker.patch("litellm.get_model_info", return_value=None)

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and reports the dangling message
        assert result.exit_code == 0
        assert "Active context contains partial/dangling messages" in result.stdout


def test_status_fails_without_session(tmp_path: Path) -> None:
    # GIVEN an empty directory with no session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert f"Error: No session file '{SESSION_FILE_NAME}' found." in result.stderr
