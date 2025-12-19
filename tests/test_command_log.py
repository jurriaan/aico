# pyright: standard

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.consts import SESSION_FILE_NAME
from aico.main import app
from aico.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from tests.helpers import save_session

runner = CliRunner()


@pytest.fixture
def session_for_log_tests(tmp_path: Path) -> Iterator[Path]:
    # GIVEN a session with 3 pairs, a dangling message after the active window start, and start_index > 0
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = [
            # Pair 0 (inactive)
            UserChatMessage(content="prompt 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(content="resp 0", mode=Mode.CONVERSATION, timestamp="t0", model="m", duration_ms=1),
            # Pair 1 (active, excluded)
            UserChatMessage(content="prompt 1 excluded", mode=Mode.CONVERSATION, timestamp="t2"),
            AssistantChatMessage(
                content="resp 1 excluded",
                mode=Mode.CONVERSATION,
                timestamp="t2",
                model="m",
                duration_ms=1,
            ),
            # Pair 2 (active, multiline)
            UserChatMessage(content="prompt 2\nsecond line", mode=Mode.CONVERSATION, timestamp="t3"),
            AssistantChatMessage(content="resp 2", mode=Mode.CONVERSATION, timestamp="t3", model="m", duration_ms=1),
            # Dangling user message (active, after start)
            UserChatMessage(content="dangling prompt", mode=Mode.CONVERSATION, timestamp="t4"),
        ]
        # Set start index to 1, so the first pair is inactive. Use absolute keyed dict for history.
        session_data = SessionData(
            model="test-model",
            chat_history={i: msg for i, msg in enumerate(history)},
            context_files=[],
            history_start_pair=1,
            excluded_pairs=[1],
        )
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)
        yield session_file


def test_log_displays_only_active_history(session_for_log_tests: Path) -> None:
    # GIVEN a session where the active context starts after the first pair
    # WHEN aico log is run
    result = runner.invoke(app, ["log"])

    # THEN it succeeds and the output is correct
    assert result.exit_code == 0

    # Normalize whitespace to single spaces for safer matching
    output = re.sub(r"\s+", " ", result.stdout).strip()

    assert "Active Context Log" in output

    # AND it does NOT show the inactive pair (ID 0)
    assert " 0 user prompt 0 " not in output
    assert " assistant resp 0 " not in output

    # AND it shows the active excluded pair (ID 1) with textual marker
    assert "1[-] user prompt 1 excluded" in output
    assert "assistant resp 1 excluded" in output

    # AND it shows the active normal pair (ID 2), truncating the prompt
    assert "2 user prompt 2" in output
    assert "second line" not in output
    assert "assistant resp 2" in output

    # AND it shows the dangling message section for ACTIVE dangling messages
    assert "Dangling messages in active context: user: dangling prompt" in output


def test_log_with_empty_history(tmp_path: Path) -> None:
    # GIVEN an empty session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN aico log is run
        result = runner.invoke(app, ["log"])

        # THEN it succeeds and prints a 'no pairs' message
        assert result.exit_code == 0
        assert "No message pairs found in active history." in result.stdout
        assert "Dangling" not in result.stdout


def test_log_with_only_dangling_messages(tmp_path: Path) -> None:
    # GIVEN a session with only a single user message
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: dict[int, ChatMessageHistoryItem] = {
            0: UserChatMessage(content="only a prompt", mode=Mode.CONVERSATION, timestamp="t0"),
        }
        session_data = SessionData(model="test-model", chat_history=history, context_files=[])
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN aico log is run
        result = runner.invoke(app, ["log"])

        # THEN it succeeds and reports no pairs and shows the dangling message
        assert result.exit_code == 0
        output = result.stdout
        assert "No message pairs found in active history." in output
        assert "Dangling messages in active context:" in output
        assert "only a prompt" in output


def test_log_fails_without_session(tmp_path: Path) -> None:
    # GIVEN an empty directory with no session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # WHEN `aico log` is run
        result = runner.invoke(app, ["log"])

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert f"Error: No session file '{SESSION_FILE_NAME}' found." in result.stderr
