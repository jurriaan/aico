# pyright: standard

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.main import app
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from aico.utils import (
    SESSION_FILE_NAME,
    SessionDataAdapter,
    get_active_history,
    save_session,
)

runner = CliRunner()


def test_history_set_with_negative_index_argument(tmp_path: Path) -> None:
    # GIVEN a session with 10 history messages (5 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(5):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico history set -2` is run
        result = runner.invoke(app, ["history", "set", "-2"])

        # THEN the command succeeds and reports starting at pair -2
        assert result.exit_code == 0
        assert "History context will now start at pair -2." in result.stdout

        # AND the history start index is set to message index 6 (start of pair 3)
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        assert updated_session_data.history_start_index == 6


def test_history_view_shows_summary_with_excluded_and_start_index(tmp_path: Path) -> None:
    # GIVEN a session with 6 messages, start index at 2, and one pair excluded after the start index
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
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
        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_index=2)
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN `aico history view` is run with color enabled for rich
        result = runner.invoke(app, ["history", "view"], color=True)

        # THEN the command succeeds and shows the correct summary
        assert result.exit_code == 0
        output = result.stdout
        # Test for key components rather than exact ANSI code-filled string
        assert "Full history summary:" in output
        assert "Total messages: 6 recorded." in output
        assert "Total excluded: 2 (across the entire history)." in output
        assert "Current context (for next prompt):" in output
        assert "Messages to be sent: 2" in output
        assert "(From an active window of 4 messages (indices 2-5), with 2 excluded via `aico undo`)" in output.replace(
            "\n", ""
        )


def test_history_view_shows_summary_with_no_excluded_messages(tmp_path: Path) -> None:
    # GIVEN a session with 4 messages, none excluded, start index at 0
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = [
            UserChatMessage(role="user", content="msg 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(
                role="assistant", content="resp 0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1
            ),
            UserChatMessage(role="user", content="msg 1", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(
                role="assistant", content="resp 1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1
            ),
        ]
        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_index=0)
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN `aico history view` is run with color enabled for rich
        result = runner.invoke(app, ["history", "view"], color=True)

        # THEN the command succeeds and shows the correct summary
        assert result.exit_code == 0
        output = result.stdout
        assert "Full history summary:" in output
        assert "Total messages: 4 recorded." in output
        assert "Total excluded: 0 (across the entire history)." in output
        assert "Current context (for next prompt):" in output
        assert "Messages to be sent: 4" in output
        assert "(From an active window of 4 messages (indices 0-3), with 0 excluded via `aico undo`)" in output.replace(
            "\n", ""
        )


def test_history_reset_sets_index_to_zero(tmp_path: Path) -> None:
    # GIVEN a session with 10 messages and the history index at 5
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        chat_history: list[ChatMessageHistoryItem] = [
            UserChatMessage(
                role="user",
                content=f"msg {i}",
                mode=Mode.CONVERSATION,
                timestamp=datetime.now(UTC).isoformat(),
            )
            for i in range(10)
        ]
        session_data = SessionData(
            model="test-model",
            context_files=[],
            chat_history=chat_history,
            history_start_index=5,
        )
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico history reset` is run
        result = runner.invoke(app, ["history", "reset"])

        # THEN the command succeeds and reports the reset
        assert result.exit_code == 0
        assert "History index reset to 0. Full chat history is now active." in result.stdout

        # AND all 10 messages are now active for the next prompt
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        active_history = get_active_history(updated_session_data)
        assert len(active_history) == 10


def test_history_set_with_positive_pair_index(tmp_path: Path) -> None:
    # GIVEN a session with 6 history messages (3 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(3):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico history set 1` is run
        result = runner.invoke(app, ["history", "set", "1"])

        # THEN the command succeeds and reports starting at pair 1
        assert result.exit_code == 0
        assert "History context will now start at pair 1." in result.stdout

        # AND the history start index is set to message index 2 (start of pair 1)
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        assert updated_session_data.history_start_index == 2


def test_history_set_to_clear_context(tmp_path: Path) -> None:
    # GIVEN a session with 4 history messages (2 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(2):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)

        # WHEN `aico history set 2` is run (where 2 is num_pairs)
        result = runner.invoke(app, ["history", "set", "2"])

        # THEN the command succeeds and confirms the context is cleared
        assert result.exit_code == 0
        assert "History context cleared (will start after the last pair)." in result.stdout

        # AND the history start index is set to 4 (the total number of messages)
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        assert updated_session_data.history_start_index == 4


@pytest.mark.parametrize(
    "invalid_input,error_message",
    [
        (
            "4",  # For 3 pairs, index 3 is valid (clear context), so 4 is the first invalid positive index.
            "Error: Index out of bounds. Valid indices are in the range 0 to 2 (or -1 to -3), or 3 to clear context.",
        ),
        (
            "-4",  # For 3 pairs, -3 is the first valid negative index, so -4 is the first invalid one.
            "Error: Index out of bounds. Valid indices are in the range 0 to 2 (or -1 to -3), or 3 to clear context.",
        ),
        ("abc", "Error: Invalid index 'abc'"),
    ],
)
def test_history_set_fails_with_invalid_index(tmp_path: Path, invalid_input: str, error_message: str) -> None:
    # GIVEN a session with 6 history messages (3 pairs)
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(3):
            history.append(UserChatMessage(role="user", content=f"p{i}", mode=Mode.CONVERSATION, timestamp=f"t{i}"))
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"r{i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"t{i}",
                    model="m",
                    duration_ms=1,
                )
            )

        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_index=1)
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)
        original_start_index = session_data.history_start_index

        # WHEN `aico history set` is run with an invalid index
        result = runner.invoke(app, ["history", "set", invalid_input])

        # THEN the command fails with a specific error
        assert result.exit_code == 1
        assert error_message in result.stderr

        # AND the history start index remains unchanged
        updated_session_data = SessionDataAdapter.validate_json(session_file.read_text())
        assert updated_session_data.history_start_index == original_start_index


@pytest.mark.parametrize(
    "command_args",
    [
        ["history", "view"],
        ["history", "reset"],
        ["history", "set", "5"],
        ["history", "log"],
    ],
)
def test_history_commands_fail_without_session(tmp_path: Path, command_args: list[str]) -> None:
    # GIVEN an empty directory with no session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # WHEN a history command is run
        result = runner.invoke(app, command_args)

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert f"Error: No session file '{SESSION_FILE_NAME}' found." in result.stderr


@pytest.fixture
def session_for_log_tests(tmp_path: Path) -> Iterator[Path]:
    # GIVEN a session with 3 pairs, a dangling message, and start_index > 0
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = [
            # Pair 0 (inactive)
            UserChatMessage(role="user", content="prompt 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(
                role="assistant", content="resp 0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1
            ),
            # Dangling user message (active)
            UserChatMessage(role="user", content="dangling prompt", mode=Mode.CONVERSATION, timestamp="t1"),
            # Pair 1 (active, excluded)
            UserChatMessage(
                role="user", content="prompt 1 excluded", mode=Mode.CONVERSATION, timestamp="t2", is_excluded=True
            ),
            AssistantChatMessage(
                role="assistant",
                content="resp 1 excluded",
                mode=Mode.CONVERSATION,
                timestamp="t2",
                model="m",
                duration_ms=1,
                is_excluded=True,
            ),
            # Pair 2 (active, multiline)
            UserChatMessage(role="user", content="prompt 2\nsecond line", mode=Mode.CONVERSATION, timestamp="t3"),
            AssistantChatMessage(
                role="assistant", content="resp 2", mode=Mode.CONVERSATION, timestamp="t3", model="m", duration_ms=1
            ),
        ]
        # Set start index to 2, so the first pair is inactive
        session_data = SessionData(model="test-model", chat_history=history, context_files=[], history_start_index=2)
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)
        yield session_file


def test_history_log_displays_active_context_only(session_for_log_tests: Path) -> None:
    # GIVEN a session where the active context starts after the first pair
    # WHEN aico history log is run
    result = runner.invoke(app, ["history", "log"])

    # THEN it succeeds and the output is correct
    assert result.exit_code == 0
    output = result.stdout

    assert "Active Context Log" in output

    # AND it does NOT show the inactive pair (ID 0)
    assert "ID" in output  # Table header
    assert "prompt 0" not in output
    assert "resp 0" not in output

    # AND it shows the active excluded pair (ID 1)
    assert "1" in output and "prompt 1 excluded" in output and "resp 1 excluded" in output

    # AND it shows the active normal pair (ID 2), truncating the prompt
    assert "2" in output and "prompt 2" in output and "second line" not in output and "resp 2" in output

    # AND it shows the dangling message section with the active dangling message
    assert "Dangling messages in active context" in output
    assert "dangling prompt" in output


def test_history_log_with_empty_active_context(tmp_path: Path) -> None:
    # GIVEN an empty session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN aico history log is run
        result = runner.invoke(app, ["history", "log"])

        # THEN it succeeds and prints a 'no pairs' message
        assert result.exit_code == 0
        assert "No message pairs found in active context." in result.stdout
        assert "Dangling" not in result.stdout


def test_history_log_with_only_dangling_messages_in_active_context(tmp_path: Path) -> None:
    # GIVEN a session with only a single user message
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = [
            UserChatMessage(role="user", content="only a prompt", mode=Mode.CONVERSATION, timestamp="t0"),
        ]
        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN aico history log is run
        result = runner.invoke(app, ["history", "log"])

        # THEN it succeeds and reports no pairs and shows the dangling message
        assert result.exit_code == 0
        output = result.stdout
        assert "No message pairs found in active context." in output
        assert "Dangling messages in active context (not part of a pair):" in output
        assert "only a prompt" in output
