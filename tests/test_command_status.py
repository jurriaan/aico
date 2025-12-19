# pyright: standard

import json
from pathlib import Path

from typer.testing import CliRunner

from aico.consts import SESSION_FILE_NAME
from aico.main import app
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from tests.helpers import save_session

runner = CliRunner()


def test_status_json_outputs_sorted_context_files(tmp_path: Path) -> None:
    """
    Tests that `aico status --json` correctly outputs a sorted list
    of context files in JSON format.
    """
    # GIVEN a session with an unsorted list of context files
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        session_data = SessionData(
            model="test-model",
            context_files=["src/file2.ts", "file1.py", "README.md"],
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # WHEN I run `aico status --json`
        result = runner.invoke(app, ["status", "--json"])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the output is a JSON object with the sorted context files
        output_data = json.loads(result.stdout)
        expected_data = {"context_files": ["README.md", "file1.py", "src/file2.ts"]}
        assert output_data == expected_data


def test_status_full_breakdown(tmp_path: Path, mocker) -> None:
    """
    Tests that the status command shows tokens, costs, and context window
    info when all data is available.
    """
    from aico.model_registry import ModelInfo

    # GIVEN a session with context files and history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        (session_dir / "file1.py").write_text("a" * 10)
        session_data = SessionData(
            model="test-model-with-cost",
            context_files=["file1.py"],
            chat_history=[
                UserChatMessage(
                    content="message 1",
                    mode=Mode.CONVERSATION,
                    timestamp="ts1",
                ),
                AssistantChatMessage(
                    content="response 1",
                    mode=Mode.CONVERSATION,
                    timestamp="ts1",
                    model="m",
                    duration_ms=1,
                ),
            ],
            history_start_pair=0,
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # Mock token counting to return fixed values:
        # system prompt (100), alignment 1 (30), alignment 2 (40), context anchors (10), chat history (50),
        #   context files (20)
        mocker.patch("aico.llm.tokens.count_tokens_for_messages", side_effect=[100, 30, 40, 10, 50, 20])

        # Mock model info to return cost and window info
        mock_info = ModelInfo(
            max_input_tokens=8192,
            input_cost_per_token=0.0001,
            output_cost_per_token=0.0001,
        )
        mocker.patch("aico.model_registry.get_model_info", return_value=mock_info)

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and prints all information
        assert result.exit_code == 0
        output = result.stdout

        # Check titles and headers
        assert "Session 'main'" in output
        assert "test-model-with-cost" in output
        assert "Tokens" in output and "(approx.)" in output and "Cost" in output and "Component" in output

        # Check component costs and tokens
        # Tokens: 100(sys) + (40 base + 10 anchors = 50 align) + 50(hist) + 20(file) = 220
        assert "100" in output and "system prompt" in output and "$0.01000" in output
        assert "50" in output and "alignment prompts" in output and "$0.00500" in output
        assert "50" in output and "chat history" in output and "$0.00500" in output
        assert "20" in output and "file1.py" in output and "$0.0020" in output

        # Check history summary
        assert "Active window: 1 pair (ID 0), 1 sent." in output

        # Check file group header
        assert "Context Files (1)" in output

        # Check total
        assert "~220" in output and "Total" in output and "$0.0220" in output

        # Check context window
        assert "Context Window" in output
        assert "8,192" in output
        assert "97% remaining" in output


def test_status_handles_unknown_model(tmp_path: Path, mocker) -> None:
    """
    Tests that the status command handles cases where model info (cost, context) is unavailable.
    """
    from aico.model_registry import ModelInfo

    # GIVEN a session with an unknown model
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        session_data = SessionData(model="unknown-model", context_files=[], chat_history=[])
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # Mock token counting
        mocker.patch("aico.llm.tokens.count_tokens_for_messages", return_value=10)

        # Mock model info to return empty info (no cost, no window)
        mocker.patch("aico.model_registry.get_model_info", return_value=ModelInfo())

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and prints the token breakdown
        assert result.exit_code == 0
        output = result.stdout
        assert "10" in output and "system prompt" in output
        # Total tokens: 10(sys) + (10 base + 10 anchors = 20 align) + 10(history) = 40
        assert "~40" in output and "Total" in output

        # AND no cost or context window information is displayed
        assert "Cost" in output  # The column header still exists
        assert "$" not in output
        assert "Context Window" not in output


def test_status_omits_excluded_messages(tmp_path: Path, mocker) -> None:
    """
    Tests that `aico status` correctly excludes messages marked with is_excluded=True
    from its token calculation and updates the summary text.
    """
    from aico.model_registry import ModelInfo

    # GIVEN a session with a mix of active and excluded history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        history = [
            UserChatMessage(content="active message", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(
                content="active resp",
                mode=Mode.CONVERSATION,
                timestamp="t2",
                model="m",
                duration_ms=1,
            ),
            UserChatMessage(content="excluded message", mode=Mode.CONVERSATION, timestamp="t3"),
            AssistantChatMessage(
                content="excluded resp",
                mode=Mode.CONVERSATION,
                timestamp="t3",
                model="m",
                duration_ms=1,
            ),
        ]
        session_data = SessionData(
            model="test-model",
            context_files=[],
            chat_history=history,
            excluded_pairs=[1],  # Exclude pair 1
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # AND the token counter is mocked
        mock_token_counter = mocker.patch("aico.llm.tokens.count_tokens_for_messages")
        # system, alignment_base1, alignment_base2, alignment_anchors, chat history
        mock_token_counter.side_effect = [100, 50, 40, 5, 20]

        mocker.patch("aico.model_registry.get_model_info", return_value=ModelInfo(max_input_tokens=1000))

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"], env={"COLUMNS": "120"})

        # THEN the command succeeds
        assert result.exit_code == 0
        output = result.stdout

        # AND the "chat history" component should have a count of 20
        assert "chat history" in output
        assert "20" in output

        # AND the total should reflect only the active messages
        # The alignment tokens will be max(50, 40) + 5 = 55. Total = 100(sys) + 55(align) + 20(hist) = 175.
        assert "~175" in output and "Total" in output

        # AND the history summary text correctly reports the exclusion
        assert "Active window: 2 pairs (IDs 0-1), 1 sent (1 excluded" in output

        # AND the reconstructed messages passed to the token counter should not contain the excluded message
        # system, align1, align2, anchors, history
        history_call = mock_token_counter.call_args_list[4]
        messages_arg = history_call.args[1]
        assert len(messages_arg) == 2
        assert "active message" in messages_arg[0]["content"]
        assert "active resp" in messages_arg[1]["content"]


def test_status_history_summary_logic(tmp_path: Path, mocker) -> None:
    from aico.model_registry import ModelInfo

    # GIVEN a session with 3 pairs, start index at 2 (msg index), one pair excluded
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        history = [
            UserChatMessage(content="msg 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(content="resp 0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1),
            UserChatMessage(content="msg 1", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(content="resp 1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1),
            UserChatMessage(content="msg 2", mode=Mode.CONVERSATION, timestamp="t2"),
            AssistantChatMessage(
                content="resp 2",
                mode=Mode.CONVERSATION,
                timestamp="t2",
                model="m",
                duration_ms=1,
            ),
        ]
        # Active context starts at Pair 1, and pair 2 is excluded
        session_data = SessionData(
            model="test-model",
            chat_history=history,
            context_files=[],
            history_start_pair=1,
            excluded_pairs=[2],
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)
        mocker.patch("aico.llm.tokens.count_tokens_for_messages", return_value=10)
        mocker.patch("aico.model_registry.get_model_info", return_value=ModelInfo())

        # WHEN `aico status` is run
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and shows the correct summary
        assert result.exit_code == 0, result.stderr
        assert "Active window: 2 pairs (IDs 1-2), 1 sent (1 excluded" in result.stdout


def test_status_handles_dangling_messages(tmp_path: Path, mocker) -> None:
    from aico.model_registry import ModelInfo

    # GIVEN a session with a dangling user message
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        history: list[ChatMessageHistoryItem] = [
            UserChatMessage(content="dangling", mode=Mode.CONVERSATION, timestamp="t1")
        ]
        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        save_session(session_dir / SESSION_FILE_NAME, session_data)
        mocker.patch("aico.llm.tokens.count_tokens_for_messages", return_value=10)
        mocker.patch("aico.model_registry.get_model_info", return_value=ModelInfo())

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
