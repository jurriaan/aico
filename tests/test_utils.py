# pyright: standard

import sys
from collections.abc import Sequence
from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.console import calculate_and_display_cost
from aico.consts import SESSION_FILE_NAME
from aico.llm.tokens import count_tokens_for_messages
from aico.main import app
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, LLMChatMessage, Mode, SessionData, TokenUsage
from tests.helpers import save_session

runner = CliRunner()


def test_aico_session_file_env_var_works(tmp_path: Path, mocker: MockerFixture) -> None:
    from aico.model_registry import ModelInfo

    # GIVEN a session file at a non-standard location
    session_dir = tmp_path / "custom" / "location"
    session_dir.mkdir(parents=True)
    session_file = session_dir / SESSION_FILE_NAME
    save_session(session_file, SessionData(model="test-model", context_files=[], chat_history=[]))

    # Avoid token counting and model fetch overhead
    mocker.patch("aico.llm.tokens.count_tokens_for_messages", return_value=10)
    mocker.patch("aico.model_registry.get_model_info", return_value=ModelInfo())

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
    from aico.model_registry import ModelInfo

    # GIVEN a session file in the current directory (normal case)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, SessionData(model="upward-search-model", context_files=[], chat_history=[]))

        # AND dependencies are mocked
        mocker.patch("aico.llm.tokens.count_tokens_for_messages", return_value=10)
        mocker.patch("aico.model_registry.get_model_info", return_value=ModelInfo())

        # AND AICO_SESSION_FILE is not set
        # WHEN we run aico status
        result = runner.invoke(app, ["status"])

        # THEN the command succeeds and finds the session file via upward search
        assert result.exit_code == 0
        assert "upward-search-model" in result.stdout


def test_calculate_and_display_cost_logic(mocker: MockerFixture) -> None:
    from aico.model_registry import ModelInfo
    from aico.models import UserChatMessage

    # GIVEN
    mocker.patch("aico.console.is_terminal", return_value=False)
    mock_print = mocker.patch("builtins.print")

    # Mock ModelInfo to return costs that result in 0.50 total
    # 100 prompt * 0.002 = 0.20
    # 50 completion * 0.006 = 0.30
    # Total = 0.50
    mock_model_info = ModelInfo(input_cost_per_token=0.002, output_cost_per_token=0.006)
    mocker.patch("aico.console.get_model_info", return_value=mock_model_info)

    chat_history: Sequence[ChatMessageHistoryItem] = [
        UserChatMessage(role="user", content="u0", mode=Mode.CONVERSATION, timestamp="t0"),
        AssistantChatMessage(
            role="assistant", content="a0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1, cost=10.0
        ),
        UserChatMessage(role="user", content="u1", mode=Mode.CONVERSATION, timestamp="t1"),
        AssistantChatMessage(
            role="assistant", content="a1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1, cost=1.0
        ),
        UserChatMessage(role="user", content="u2", mode=Mode.CONVERSATION, timestamp="t2"),
        AssistantChatMessage(
            role="assistant", content="a2", mode=Mode.CONVERSATION, timestamp="t2", model="m", duration_ms=1, cost=2.0
        ),
    ]
    token_usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    model_name = "test-model"

    # Construct a modern SessionData object that starts at the second pair
    session_data = SessionData(
        model=model_name,
        chat_history=list(chat_history),
        history_start_pair=1,  # Start at pair 1 {u1, a1}
        excluded_pairs=[2],  # Exclude pair 2 {u2, a2}. Cost should still be counted.
    )

    # WHEN calculate_and_display_cost is called with the new signature
    message_cost = calculate_and_display_cost(token_usage, model_name, session_data)

    # THEN the returned cost for the new message is correct
    assert message_cost == 0.50

    # AND the printed output string to stderr is correctly formatted
    # Historical window cost = 1.0 (a1) + 2.0 (a2) = 3.0
    # Total current chat cost = 3.0 (history) + 0.5 (new message) = 3.50
    expected_info_str = "Tokens: 100 sent, 50 received. Cost: $0.50, current chat: $3.50"
    mock_print.assert_called_with(expected_info_str, file=sys.stderr)


def test_count_tokens_for_messages(mocker: MockerFixture) -> None:
    # WHEN calling count_tokens_for_messages
    # content length is 11 ("hello world")
    messages: list[LLMChatMessage] = [{"role": "user", "content": "hello world"}]
    model = "test-model"
    token_count = count_tokens_for_messages(model, messages)

    # THEN heuristic is applied: 11 // 4 = 2
    assert token_count == 2


def test_calculate_and_display_cost_shows_cached_tokens(mocker: MockerFixture) -> None:
    # GIVEN
    mocker.patch("aico.console.is_terminal", return_value=False)
    mock_print = mocker.patch("builtins.print")

    from aico.model_registry import ModelInfo
    from aico.models import UserChatMessage

    # Mock ModelInfo to return zero costs
    mock_model_info = ModelInfo(input_cost_per_token=0.0, output_cost_per_token=0.0)
    mocker.patch("aico.console.get_model_info", return_value=mock_model_info)

    chat_history: Sequence[ChatMessageHistoryItem] = [
        UserChatMessage(role="user", content="u0", mode=Mode.CONVERSATION, timestamp="t0"),
        AssistantChatMessage(
            role="assistant", content="a0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1, cost=0.0
        ),
    ]
    token_usage = TokenUsage(prompt_tokens=2048, cached_tokens=1024, completion_tokens=100, total_tokens=2148)
    model_name = "test-model"

    # Construct a modern SessionData object
    session_data = SessionData(
        model=model_name,
        chat_history=list(chat_history),
        history_start_pair=0,
        excluded_pairs=[],
    )

    # WHEN calculate_and_display_cost is called with cached tokens
    message_cost = calculate_and_display_cost(token_usage, model_name, session_data)

    # THEN the returned cost for the new message is correct
    assert message_cost == 0.0

    # AND the printed output string to stderr contains the cached token info
    expected_info_str = "Tokens: 2.0k (1.0k cached) sent, 100 received. Cost: $0.00, current chat: $0.00"
    mock_print.assert_called_with(expected_info_str, file=sys.stderr)
