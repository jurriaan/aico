# pyright: standard

import sys
from collections.abc import Sequence
from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.lib.models import AssistantChatMessage, ChatMessageHistoryItem, LLMChatMessage, Mode, SessionData, TokenUsage
from aico.lib.session import SESSION_FILE_NAME, save_session
from aico.main import app
from aico.utils import calculate_and_display_cost, count_tokens_for_messages

runner = CliRunner()


def test_aico_session_file_env_var_works(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session file at a non-standard location
    session_dir = tmp_path / "custom" / "location"
    session_dir.mkdir(parents=True)
    session_file = session_dir / SESSION_FILE_NAME
    save_session(session_file, SessionData(model="test-model", context_files=[], chat_history=[]))

    # AND litellm dependencies are mocked
    mocker.patch("aico.utils.count_tokens_for_messages", return_value=10)
    mocker.patch("litellm.get_model_info", return_value=None)

    # WHEN AICO_SESSION_FILE is set to that absolute path
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": str(session_file.resolve())})

        # AND we run aico status (which needs to find the session file)
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and uses the session file from the env var
        assert result.exit_code == 0
        assert "test-model" in result.stdout


def test_aico_session_file_env_var_fails_for_relative_path(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a relative path in AICO_SESSION_FILE
    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": "relative/path.json"})

        # WHEN we run aico status
        result = runner.invoke(app, ["status"])

        # THEN the command fails with a clear error
        assert result.exit_code == 1
        assert "AICO_SESSION_FILE must be an absolute path" in result.stderr


def test_aico_session_file_env_var_fails_for_nonexistent_file(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN an absolute path to a non-existent file in AICO_SESSION_FILE
    nonexistent_file = tmp_path / "does_not_exist.json"

    with runner.isolated_filesystem(temp_dir=tmp_path):
        mocker.patch.dict("os.environ", {"AICO_SESSION_FILE": str(nonexistent_file.resolve())})

        # WHEN we run aico status
        result = runner.invoke(app, ["status"])

        # THEN the command fails with a clear error
        assert result.exit_code == 1
        assert "Session file specified in AICO_SESSION_FILE does not exist" in result.stderr


def test_aico_session_file_env_var_not_set_uses_upward_search(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session file in the current directory (normal case)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, SessionData(model="upward-search-model", context_files=[], chat_history=[]))

        # AND litellm dependencies are mocked
        mocker.patch("aico.utils.count_tokens_for_messages", return_value=10)
        mocker.patch("litellm.get_model_info", return_value=None)

        # AND AICO_SESSION_FILE is not set
        # WHEN we run aico status
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and finds the session file via upward search
        assert result.exit_code == 0
        assert "upward-search-model" in result.stdout


def test_get_active_history_filters_and_slices() -> None:
    # GIVEN a SessionData object with a mix of messages
    from aico.lib.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
    from aico.utils import get_active_history

    history = [
        UserChatMessage(role="user", content="msg 0 - before start", mode=Mode.RAW, timestamp="t0"),  # before start
        UserChatMessage(role="user", content="msg 1 - active", mode=Mode.RAW, timestamp="t1"),  # after start
        UserChatMessage(
            role="user", content="msg 2 - excluded", mode=Mode.RAW, timestamp="t2", is_excluded=True
        ),  # after start, excluded
        AssistantChatMessage(
            role="assistant",
            content="resp 2 - excluded",
            mode=Mode.RAW,
            timestamp="t3",
            model="m",
            duration_ms=1,
            is_excluded=True,
        ),
        UserChatMessage(role="user", content="msg 3 - active", mode=Mode.RAW, timestamp="t4"),  # after start
    ]
    session_data = SessionData(
        model="test",
        context_files=[],
        chat_history=history,
        history_start_index=1,
    )

    # WHEN get_active_history is called
    active_history = get_active_history(session_data)

    # THEN the returned list contains only the correct messages
    assert len(active_history) == 2
    assert active_history[0].content == "msg 1 - active"
    assert active_history[1].content == "msg 3 - active"


def test_calculate_and_display_cost_logic(mocker: MockerFixture) -> None:
    # GIVEN
    mocker.patch("aico.utils.is_terminal", return_value=False)
    mock_print = mocker.patch("builtins.print")

    # Mock the entire litellm module by injecting a mock into sys.modules.
    # This is the correct way to mock a module that is imported inside a function.
    mock_litellm = mocker.MagicMock()
    mock_litellm.completion_cost.return_value = 0.50
    mocker.patch.dict("sys.modules", {"litellm": mock_litellm})

    chat_history: Sequence[ChatMessageHistoryItem] = [
        # This message is before the start index, its cost should be ignored
        AssistantChatMessage(
            role="assistant", content="a0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1, cost=10.0
        ),
        # These messages are in the window. Their costs should be summed.
        AssistantChatMessage(
            role="assistant", content="a1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1, cost=1.0
        ),
        AssistantChatMessage(
            role="assistant",
            content="a2-excluded",
            mode=Mode.CONVERSATION,
            timestamp="t2",
            model="m",
            is_excluded=True,  # Cost should still be counted
            duration_ms=1,
            cost=2.0,
        ),
    ]
    token_usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    history_start_index = 1  # Start from the second message (index 1)
    model_name = "test-model"

    # WHEN calculate_and_display_cost is called
    message_cost = calculate_and_display_cost(token_usage, model_name, chat_history, history_start_index)

    # THEN the returned cost for the new message should be correct
    assert message_cost == 0.50

    # AND the cost calculation for the new message should have been called once
    mock_litellm.completion_cost.assert_called_once()
    actual_call_args = mock_litellm.completion_cost.call_args.kwargs["completion_response"]
    assert actual_call_args["usage"]["prompt_tokens"] == 100
    assert actual_call_args["model"] == model_name

    # AND the printed output string to stderr should be correctly formatted
    # Historical window cost = 1.0 (a1) + 2.0 (a2) = 3.0
    # Total current chat cost = 3.0 (history) + 0.5 (new message) = 3.50
    expected_info_str = "Tokens: 100 sent, 50 received. Cost: $0.50, current chat: $3.50"
    mock_print.assert_called_with(expected_info_str, file=sys.stderr)


def test_count_tokens_for_messages(mocker: MockerFixture) -> None:
    # GIVEN a mocked litellm.token_counter
    mock_litellm_counter = mocker.patch("litellm.token_counter", return_value=123)

    # WHEN calling count_tokens_for_messages
    messages: list[LLMChatMessage] = [{"role": "user", "content": "hello world"}]
    model = "test-model"
    token_count = count_tokens_for_messages(model, messages)

    # THEN litellm.token_counter is called with the correct arguments
    mock_litellm_counter.assert_called_once_with(model=model, messages=messages)

    # AND the result is returned
    assert token_count == 123
