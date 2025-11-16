# pyright: standard
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
from aico.lib.models import Mode, SessionData
from aico.lib.session import SESSION_FILE_NAME, SessionDataAdapter
from aico.main import app

runner = CliRunner()


def load_session_data(session_file: Path) -> SessionData:
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

    # AND the last pair index is added to the excluded_pairs list
    final_session = load_session_data(session_file)
    assert final_session.excluded_pairs == [1]


def test_undo_with_positive_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    session_file = session_with_two_pairs

    # WHEN `aico undo 0` is run
    result = runner.invoke(app, ["undo", "0"])

    # THEN the command succeeds and confirms excluding the first pair (0)
    assert result.exit_code == 0
    assert "Marked pair at index 0 as excluded." in result.stdout

    # AND the first pair index is added to the excluded_pairs list
    final_session = load_session_data(session_file)
    assert final_session.excluded_pairs == [0]


def test_undo_with_negative_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    session_file = session_with_two_pairs

    # WHEN `aico undo -2` is run
    result = runner.invoke(app, ["undo", "-2"])

    # THEN the command succeeds and confirms excluding the first pair
    # The resolved index of -2 in a 2-pair list is 0.
    assert result.exit_code == 0
    assert "Marked pair at index 0 as excluded." in result.stdout

    # AND the first pair index is added to the excluded_pairs list
    final_session = load_session_data(session_file)
    assert final_session.excluded_pairs == [0]


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


def test_undo_can_exclude_pair_before_active_window_shared_history(tmp_path: Path) -> None:
    # GIVEN a shared-history session with 2 pairs and an active window starting at pair 1
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
            excluded_pairs=[],
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

        # WHEN `aico undo 0` is run, targeting a pair before the active window
        result = runner.invoke(app, ["undo", "0"])

        # THEN it should succeed and mark pair 0 as excluded
        assert result.exit_code == 0
        assert "Marked pair at index 0 as excluded." in result.stdout

        # AND the underlying view should have pair 0 in excluded_pairs
        updated_view = load_view(view_path)
        assert updated_view.excluded_pairs == [0]
