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
from aico.lib.session import SESSION_FILE_NAME, SessionDataAdapter, save_session
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


def test_undo_multiple_indices(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs, none excluded
    session_file = session_with_two_pairs

    # WHEN `aico undo 0 1` is run
    result = runner.invoke(app, ["undo", "0", "1"])

    # THEN the command succeeds and both pairs are excluded
    assert result.exit_code == 0
    assert "Marked 2 pairs as excluded: 0, 1" in result.stdout

    # AND both indices are in excluded_pairs
    final_session = load_session_data(session_file)
    assert set(final_session.excluded_pairs) == {0, 1}


def test_undo_negative_and_positive_mix(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    session_file = session_with_two_pairs

    # WHEN `aico undo 0 -1` is run (-1 resolves to 1)
    result = runner.invoke(app, ["undo", "0", "-1"])

    # THEN both pairs are excluded
    assert result.exit_code == 0
    assert "Marked 2 pairs as excluded: 0, 1" in result.stdout

    final_session = load_session_data(session_file)
    assert set(final_session.excluded_pairs) == {0, 1}


def test_undo_range_syntax(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    session_file = session_with_two_pairs

    # WHEN `aico undo 0..1` is run
    result = runner.invoke(app, ["undo", "0..1"])

    # THEN both pairs are excluded
    assert result.exit_code == 0
    assert "Marked 2 pairs as excluded: 0, 1" in result.stdout

    final_session = load_session_data(session_file)
    assert final_session.excluded_pairs == [0, 1]


def test_undo_negative_range(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    session_file = session_with_two_pairs

    # WHEN `aico undo -2..-1` is run
    result = runner.invoke(app, ["undo", "-2..-1"])

    # THEN both pairs are excluded
    assert result.exit_code == 0
    assert "Marked 2 pairs as excluded: 0, 1" in result.stdout

    final_session = load_session_data(session_file)
    assert final_session.excluded_pairs == [0, 1]


def test_undo_idempotent_multiple(session_with_two_pairs: Path) -> None:
    # GIVEN a session where pair 0 is already excluded
    session_file = session_with_two_pairs
    session_data = load_session_data(session_file)
    session_data.excluded_pairs = [0]
    save_session(session_file, session_data)

    # WHEN `aico undo 0 1` is run (0 already excluded, 1 is new)
    result = runner.invoke(app, ["undo", "0", "1"])

    # THEN only the new one is reported as changed
    assert result.exit_code == 0
    assert "Marked pair at index 1 as excluded." in result.stdout

    final_session = load_session_data(session_file)
    assert set(final_session.excluded_pairs) == {0, 1}


def test_undo_all_already_excluded(session_with_two_pairs: Path) -> None:
    # GIVEN both pairs already excluded
    session_file = session_with_two_pairs
    session_data = load_session_data(session_file)
    session_data.excluded_pairs = [0, 1]
    save_session(session_file, session_data)

    # WHEN `aico undo 0 1` is run
    result = runner.invoke(app, ["undo", "0", "1"])

    # THEN no changes, but still succeeds
    assert result.exit_code == 0
    assert "No changes made (specified pairs were already excluded)." in result.stdout

    final_session = load_session_data(session_file)
    assert set(final_session.excluded_pairs) == {0, 1}


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
    assert "No changes made (specified pairs were already excluded)." in result2.stdout


def test_undo_fails_with_invalid_index_format(session_with_two_pairs: Path) -> None:
    # GIVEN a session
    # WHEN `aico undo` is run with a non-integer index
    result = runner.invoke(app, ["undo", "abc"])

    # THEN it fails with a parsing error
    assert result.exit_code == 1
    assert "Error: Invalid index 'abc'. Must be an integer." in result.stderr


def test_undo_mixed_sign_range_fails_safely(session_with_two_pairs: Path) -> None:
    """
    Ensures that ambiguous mixed-sign ranges (e.g. 0..-1) are NOT expanded
    incorrectly, but instead cause a validation error.
    """
    # GIVEN a session with pairs 0 and 1

    # WHEN running undo with a mixed-sign range
    result = runner.invoke(app, ["undo", "0..-1"])

    # THEN the command should fail
    assert result.exit_code == 1

    # AND the error should come from resolve_pair_index rejecting the unexpanded string
    # (It sees "0..-1" as a string, tries to convert to int, and fails)
    assert "Error: Invalid index '0..-1'" in result.stderr


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
            history_start_pair=1,  # Active window starts at pair 1
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
