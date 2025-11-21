# pyright: standard
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.historystore import (
    HistoryStore,
    SessionView,
    append_pair_to_view,
    load_view,
    save_view,
    switch_active_pointer,
)
from aico.historystore.models import HistoryRecord
from aico.lib.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
from aico.lib.session import SESSION_FILE_NAME, SessionDataAdapter, save_session
from aico.main import app

runner = CliRunner()


@pytest.fixture
def session_with_excluded_pairs(tmp_path: Path) -> Iterator[Path]:
    """Creates a session with 2 pairs, both excluded, within an isolated filesystem."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = []
        for i in range(2):
            history.append(
                UserChatMessage(
                    role="user",
                    content=f"user prompt {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"ts{i}",
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
                )
            )
        session_data = SessionData(model="test", context_files=[], chat_history=history, excluded_pairs=[0, 1])
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)
        yield session_file


def _load_session_data(session_file: Path) -> SessionData:
    return SessionDataAdapter.validate_json(session_file.read_text())


def test_redo_default_marks_last_pair_included(session_with_excluded_pairs: Path) -> None:
    # GIVEN a session with two excluded pairs
    session_file = session_with_excluded_pairs

    # WHEN `aico redo` is run with no arguments (defaults to -1)
    result = runner.invoke(app, ["redo"])

    # THEN the command succeeds and confirms re-including the last pair (-1)
    assert result.exit_code == 0
    # The resolved index of -1 in a 2-pair list is 1.
    assert "Re-included pair at index 1 in context." in result.stdout

    # AND only the last pair is re-included (pair 0 remains excluded)
    final_session = _load_session_data(session_file)
    assert final_session.excluded_pairs == [0]


def test_redo_multiple_indices(session_with_excluded_pairs: Path) -> None:
    # GIVEN a session with two excluded pairs
    session_file = session_with_excluded_pairs

    # WHEN `aico redo 0 1` is run
    result = runner.invoke(app, ["redo", "0", "1"])

    # THEN both pairs are re-included (excluded_pairs empty)
    assert result.exit_code == 0
    assert "Re-included pairs: 0, 1" in result.stdout

    final_session = _load_session_data(session_file)
    assert final_session.excluded_pairs == []


def test_redo_negative_and_positive_mix(session_with_excluded_pairs: Path) -> None:
    # GIVEN a session with two excluded pairs
    session_file = session_with_excluded_pairs

    # WHEN `aico redo 0 -1` is run (-1 resolves to 1)
    result = runner.invoke(app, ["redo", "0", "-1"])

    # THEN both are re-included
    assert result.exit_code == 0
    assert "Re-included pairs: 0, 1" in result.stdout

    final_session = _load_session_data(session_file)
    assert final_session.excluded_pairs == []


def test_redo_idempotent_multiple(session_with_excluded_pairs: Path) -> None:
    # GIVEN a session where pair 1 is already included (only 0 excluded)
    session_file = session_with_excluded_pairs
    session_data = _load_session_data(session_file)
    session_data.excluded_pairs = [0]  # 1 already included
    save_session(session_file, session_data)

    # WHEN `aico redo 0 1` is run
    result = runner.invoke(app, ["redo", "0", "1"])

    # THEN only the new one (0) is reported
    assert result.exit_code == 0
    assert "Re-included pair at index 0 in context." in result.stdout

    final_session = _load_session_data(session_file)
    assert final_session.excluded_pairs == []


def test_redo_all_already_included(session_with_excluded_pairs: Path) -> None:
    # GIVEN no pairs excluded
    session_file = session_with_excluded_pairs
    session_data = _load_session_data(session_file)
    session_data.excluded_pairs = []
    save_session(session_file, session_data)

    # WHEN `aico redo 0 1` is run
    result = runner.invoke(app, ["redo", "0", "1"])

    # THEN no changes
    assert result.exit_code == 0
    assert "No changes made (specified pairs were already active)." in result.stdout

    final_session = _load_session_data(session_file)
    assert final_session.excluded_pairs == []


def test_redo_with_positive_index(session_with_excluded_pairs: Path) -> None:
    # GIVEN a session with two excluded pairs
    session_file = session_with_excluded_pairs

    # WHEN `aico redo 0` is run
    result = runner.invoke(app, ["redo", "0"])

    # THEN the command succeeds and confirms re-including the first pair (0)
    assert result.exit_code == 0
    assert "Re-included pair at index 0 in context." in result.stdout

    # AND only the first pair is re-included (pair 1 remains excluded)
    final_session = _load_session_data(session_file)
    assert final_session.excluded_pairs == [1]


def test_redo_with_negative_index(session_with_excluded_pairs: Path) -> None:
    # GIVEN a session with two excluded pairs
    session_file = session_with_excluded_pairs

    # WHEN `aico redo -2` is run
    result = runner.invoke(app, ["redo", "-2"])

    # THEN the command succeeds and confirms re-including the first pair
    # The resolved index of -2 in a 2-pair list is 0.
    assert result.exit_code == 0
    assert "Re-included pair at index 0 in context." in result.stdout

    # AND only the first pair is re-included
    final_session = _load_session_data(session_file)
    assert final_session.excluded_pairs == [1]


def test_redo_fails_on_empty_history(tmp_path: Path) -> None:
    # GIVEN an empty initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN `aico redo` is run
        result = runner.invoke(app, ["redo"])

        # THEN the command fails with a "no pairs" error
        assert result.exit_code == 1
        assert "Error: No message pairs found in history." in result.stderr


@pytest.mark.parametrize("invalid_index", ["99", "-99"])
def test_redo_fails_with_out_of_bounds_index(session_with_excluded_pairs: Path, invalid_index: str) -> None:
    # GIVEN a session with two excluded pairs
    # WHEN `aico redo` is run with an out-of-bounds index
    result = runner.invoke(app, ["redo", invalid_index])

    # THEN it fails with a clear error message
    assert result.exit_code == 1
    assert f"Error: Pair at index {invalid_index} not found." in result.stderr


def test_redo_on_already_active_pair_is_idempotent(session_with_excluded_pairs: Path) -> None:
    # GIVEN a session with two excluded pairs
    # WHEN `aico redo -1` is run the first time
    result1 = runner.invoke(app, ["redo", "-1"])
    # The resolved index of -1 in a 2-pair list is 1.
    assert result1.exit_code == 0
    assert "Re-included pair at index 1 in context." in result1.stdout

    # AND WHEN `aico redo -1` is run a second time
    result2 = runner.invoke(app, ["redo", "-1"])

    # THEN it succeeds but reports that no changes were made
    assert result2.exit_code == 0
    assert "No changes made (specified pairs were already active)." in result2.stdout


def test_redo_fails_with_invalid_index_format(session_with_excluded_pairs: Path) -> None:
    # GIVEN a session
    # WHEN `aico redo` is run with a non-integer index
    result = runner.invoke(app, ["redo", "abc"])

    # THEN it fails with a parsing error
    assert result.exit_code == 1
    assert "Error: Invalid index 'abc'. Must be an integer." in result.stderr


def test_redo_can_include_pair_before_active_window_shared_history(tmp_path: Path) -> None:
    # GIVEN a shared-history session with 2 pairs, both excluded, and an active window starting at pair 1
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        project_root = Path(td)
        history_root = project_root / ".aico" / "history"
        sessions_dir = project_root / ".aico" / "sessions"
        history_root.mkdir(parents=True, exist_ok=True)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        store = HistoryStore(history_root)
        view = SessionView(
            model="test-model",
            context_files=[],
            message_indices=[],
            history_start_pair=1,
            excluded_pairs=[0, 1],
        )

        for i in range(2):
            user_record = HistoryRecord(
                role="user",
                content=f"prompt {i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
            )
            assistant_record = HistoryRecord(
                role="assistant",
                content=f"response {i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
                model="test-model",
                duration_ms=1,
            )
            _ = append_pair_to_view(store, view, user_record, assistant_record)

        view_path = sessions_dir / "main.json"
        save_view(view_path, view)
        session_file = project_root / SESSION_FILE_NAME
        switch_active_pointer(session_file, view_path)

        # WHEN `aico redo 0` is run, targeting a pair before the active window
        result = runner.invoke(app, ["redo", "0"])

        # THEN it should succeed and re-include pair 0
        assert result.exit_code == 0
        assert "Re-included pair at index 0 in context." in result.stdout

        # AND the underlying view should have only pair 1 remaining in excluded_pairs
        updated_view = load_view(view_path)
        assert updated_view.excluded_pairs == [1]
