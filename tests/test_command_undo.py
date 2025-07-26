# pyright: standard
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.lib.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
from aico.lib.session import SESSION_FILE_NAME, SessionDataAdapter, save_session
from aico.main import app

runner = CliRunner()


@pytest.fixture
def session_with_two_pairs(tmp_path: Path) -> Iterator[Path]:
    """Creates a session with 2 user/assistant pairs within an isolated filesystem."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = []
        for i in range(2):
            history.append(
                UserChatMessage(
                    role="user",
                    content=f"user prompt {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"ts{i}",
                    is_excluded=False,
                )
            )
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"assistant response {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"ts{i}",
                    model="test-model",
                    duration_ms=100,
                    is_excluded=False,
                )
            )
        session_data = SessionData(model="test", context_files=[], chat_history=history)
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)
        yield session_file


def _load_session_data(session_file: Path) -> SessionData:
    return SessionDataAdapter.validate_json(session_file.read_text())


def test_undo_default_marks_last_pair_excluded(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    session_file = session_with_two_pairs

    # WHEN `aico undo` is run with no arguments (defaults to -1)
    result = runner.invoke(app, ["undo"])

    # THEN the command succeeds and confirms excluding the last pair (-1)
    assert result.exit_code == 0
    # The resolved index of -1 in a 2-pair list is 1.
    assert "Marked pair at index 1 as excluded." in result.stdout

    # AND only the last pair is excluded
    final_session = _load_session_data(session_file)
    assert final_session.chat_history[0].is_excluded is False
    assert final_session.chat_history[1].is_excluded is False
    assert final_session.chat_history[2].is_excluded is True
    assert final_session.chat_history[3].is_excluded is True


def test_undo_with_positive_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    session_file = session_with_two_pairs

    # WHEN `aico undo 0` is run
    result = runner.invoke(app, ["undo", "0"])

    # THEN the command succeeds and confirms excluding the first pair (0)
    assert result.exit_code == 0
    assert "Marked pair at index 0 as excluded." in result.stdout

    # AND only the first pair is excluded
    final_session = _load_session_data(session_file)
    assert final_session.chat_history[0].is_excluded is True
    assert final_session.chat_history[1].is_excluded is True
    assert final_session.chat_history[2].is_excluded is False
    assert final_session.chat_history[3].is_excluded is False


def test_undo_with_negative_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    session_file = session_with_two_pairs

    # WHEN `aico undo -2` is run
    result = runner.invoke(app, ["undo", "-2"])

    # THEN the command succeeds and confirms excluding the first pair
    # The resolved index of -2 in a 2-pair list is 0.
    assert result.exit_code == 0
    assert "Marked pair at index 0 as excluded." in result.stdout

    # AND only the first pair is excluded
    final_session = _load_session_data(session_file)
    assert final_session.chat_history[0].is_excluded is True
    assert final_session.chat_history[1].is_excluded is True
    assert final_session.chat_history[2].is_excluded is False
    assert final_session.chat_history[3].is_excluded is False


def test_undo_fails_on_empty_history(tmp_path: Path) -> None:
    # GIVEN an empty initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN `aico undo` is run
        result = runner.invoke(app, ["undo"])

        # THEN the command fails with a "no pairs" error
        assert result.exit_code == 1
        assert "Error: No message pairs found in history." in result.stderr


@pytest.mark.parametrize("invalid_index", ["99", "-99"])
def test_undo_fails_with_out_of_bounds_index(session_with_two_pairs: Path, invalid_index: str) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico undo` is run with an out-of-bounds index
    result = runner.invoke(app, ["undo", invalid_index])

    # THEN it fails with a clear error message
    assert result.exit_code == 1
    assert f"Error: Pair at index {invalid_index} not found." in result.stderr


def test_undo_on_already_excluded_pair_is_idempotent(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico undo -1` is run the first time
    result1 = runner.invoke(app, ["undo", "-1"])
    # The resolved index of -1 in a 2-pair list is 1.
    assert result1.exit_code == 0
    assert "Marked pair at index 1 as excluded." in result1.stdout

    # AND WHEN `aico undo -1` is run a second time
    result2 = runner.invoke(app, ["undo", "-1"])

    # THEN it succeeds but reports that no changes were made
    assert result2.exit_code == 0
    assert "Pair at index 1 is already excluded. No changes made." in result2.stdout


def test_undo_fails_with_invalid_index_format(session_with_two_pairs: Path) -> None:
    # GIVEN a session
    # WHEN `aico undo` is run with a non-integer index
    result = runner.invoke(app, ["undo", "abc"])

    # THEN it fails with a parsing error
    assert result.exit_code == 1
    assert "Error: Invalid index 'abc'. Must be an integer." in result.stderr
