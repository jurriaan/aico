# pyright: standard

from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.historystore import HistoryRecord, HistoryStore, SessionView, load_view, save_view
from aico.lib.models import Mode
from aico.main import app

runner = CliRunner()


@pytest.fixture
def shared_writable_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Creates a temporary project directory with a shared-history session and enables write support.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("AICO_EXPERIMENTAL_WRITES", "1")

    # Minimal shared-history workspace with one pair
    history_root = project_dir / ".aico" / "history"
    sessions_dir = project_dir / ".aico" / "sessions"
    history_root.mkdir(parents=True)
    sessions_dir.mkdir(parents=True)

    store = HistoryStore(history_root)
    u0 = store.append(HistoryRecord(role="user", content="p0", mode=Mode.CONVERSATION))
    a0 = store.append(HistoryRecord(role="assistant", content="r0", mode=Mode.CONVERSATION, model="m"))
    view = SessionView(model="m", context_files=[], message_indices=[u0, a0], history_start_pair=0, excluded_pairs=[])
    view_path = sessions_dir / "main.json"
    save_view(view_path, view)

    pointer_file = project_dir / ".ai_session.json"
    # Write a pointer file with a relative path
    pointer_file.write_text('{"type":"aico_session_pointer_v1","path":"./.aico/sessions/main.json"}', encoding="utf-8")

    return project_dir


def _load_view(project_dir: Path) -> SessionView:
    return load_view(project_dir / ".aico" / "sessions" / "main.json")


def test_append_pair_via_ask_in_writable_shared_history(shared_writable_project: Path, mocker: MockerFixture) -> None:
    # GIVEN a writable shared-history session and mocked LLM execution
    from aico.lib.models import InteractionResult

    mocker.patch(
        "aico.commands.prompt.execute_interaction",
        return_value=InteractionResult(
            content="resp new",
            display_items=[],
            token_usage=None,
            cost=None,
            duration_ms=0,
            unified_diff=None,
        ),
    )

    # WHEN we run a mutating command that appends a pair
    result = runner.invoke(app, ["ask", "prompt new"])
    assert result.exit_code == 0, result.stderr

    # THEN the view contains the appended pair
    view = _load_view(shared_writable_project)
    assert len(view.message_indices) == 4

    # AND records exist with correct roles and content
    store = HistoryStore(shared_writable_project / ".aico" / "history")
    u_idx, a_idx = view.message_indices[-2], view.message_indices[-1]
    assert store.read(u_idx).role == "user" and store.read(u_idx).content == "prompt new"
    assert store.read(a_idx).role == "assistant" and store.read(a_idx).content == "resp new"


def test_undo_and_redo_toggle_exclusions(shared_writable_project: Path, mocker: MockerFixture) -> None:
    # GIVEN: ensure there are two pairs by appending one
    from aico.lib.models import InteractionResult

    mocker.patch(
        "aico.commands.prompt.execute_interaction",
        return_value=InteractionResult(
            content="resp extra",
            display_items=[],
            token_usage=None,
            cost=None,
            duration_ms=0,
            unified_diff=None,
        ),
    )
    _ = runner.invoke(app, ["ask", "p1"])

    # WHEN excluding the last pair
    res_undo = runner.invoke(app, ["undo"])
    assert res_undo.exit_code == 0, res_undo.stderr

    # THEN the last pair is in excluded_pairs
    view = _load_view(shared_writable_project)
    assert view.excluded_pairs == [1]

    # WHEN re-including the last pair
    res_redo = runner.invoke(app, ["redo"])
    assert res_redo.exit_code == 0, res_redo.stderr

    # THEN exclusions are cleared
    view2 = _load_view(shared_writable_project)
    assert view2.excluded_pairs == []


def test_set_history_updates_history_start_pair(shared_writable_project: Path, mocker: MockerFixture) -> None:
    # GIVEN: ensure two pairs exist
    from aico.lib.models import InteractionResult

    mocker.patch(
        "aico.commands.prompt.execute_interaction",
        return_value=InteractionResult(
            content="resp 2",
            display_items=[],
            token_usage=None,
            cost=None,
            duration_ms=0,
            unified_diff=None,
        ),
    )
    _ = runner.invoke(app, ["ask", "p2"])

    # WHEN setting history start to the second pair
    res = runner.invoke(app, ["set-history", "1"])
    assert res.exit_code == 0, res.stderr

    # THEN view history_start_pair is updated
    view = _load_view(shared_writable_project)
    assert view.history_start_pair == 1


def test_edit_updates_store_and_view(shared_writable_project: Path, mocker: MockerFixture) -> None:
    # GIVEN: ensure there's a recent pair to edit
    from aico.lib.models import InteractionResult

    mocker.patch("aico.commands.edit.is_input_terminal", return_value=True)
    mocker.patch(
        "aico.commands.prompt.execute_interaction",
        return_value=InteractionResult(
            content="resp to edit",
            display_items=[],
            token_usage=None,
            cost=None,
            duration_ms=0,
            unified_diff=None,
        ),
    )
    _ = runner.invoke(app, ["ask", "p-edit"])

    # AND mock the editor to write new content
    def mock_editor(command_parts: list[str], **kwargs: object):
        temp_file_path = Path(command_parts[-1])
        temp_file_path.write_text("edited assistant content")
        proc = mocker.MagicMock()
        proc.returncode = 0
        return proc

    mocker.patch("aico.commands.edit.subprocess.run", side_effect=mock_editor)

    # WHEN editing the last assistant response
    res_edit = runner.invoke(app, ["edit"])
    assert res_edit.exit_code == 0, res_edit.stderr

    # THEN the content seen by `aico last` is the edited one
    res_last = runner.invoke(app, ["last"])
    assert res_last.exit_code == 0
    assert res_last.stdout.strip() == "edited assistant content"


def test_context_files_update_via_add(shared_writable_project: Path, mocker: MockerFixture) -> None:
    # GIVEN a new file on disk
    extra = shared_writable_project / "extra.txt"
    extra.write_text("hello", encoding="utf-8")

    # WHEN adding it to context
    res_add = runner.invoke(app, ["add", "extra.txt"])
    assert res_add.exit_code == 0, res_add.stderr

    # THEN view context_files includes the file
    view = _load_view(shared_writable_project)
    assert "extra.txt" in view.context_files
