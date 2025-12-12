# pyright: standard

from pathlib import Path

from typer.testing import CliRunner

from aico.historystore import HistoryRecord, HistoryStore, SessionView, save_view, switch_active_pointer
from aico.main import app
from aico.models import Mode

runner = CliRunner()


def _setup_shared_history(root: Path) -> None:
    """
    Creates a minimal shared-history setup with a single 'main' view.
    """

    history_root = root / ".aico" / "history"
    sessions_dir = root / ".aico" / "sessions"
    history_root.mkdir(parents=True)
    sessions_dir.mkdir(parents=True)

    store = HistoryStore(history_root)
    u_idx = store.append(HistoryRecord(role="user", content="prompt 0", mode=Mode.CONVERSATION))
    a_idx = store.append(HistoryRecord(role="assistant", content="resp 0", mode=Mode.CONVERSATION, model="m"))

    view = SessionView(model="m", message_indices=[u_idx, a_idx], context_files=[])
    main_view_path = sessions_dir / "main.json"
    save_view(main_view_path, view)
    pointer_file = root / ".ai_session.json"
    switch_active_pointer(pointer_file, main_view_path)


def test_session_list_and_fork_and_switch(tmp_path: Path) -> None:
    # GIVEN a shared-history workspace
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _setup_shared_history(project_dir)

    with runner.isolated_filesystem(temp_dir=project_dir):
        # WHEN listing sessions
        result_list = runner.invoke(app, ["session-list"])
        assert result_list.exit_code == 0
        assert "main (active)" in result_list.stdout

        # WHEN forking a new branch
        result_fork = runner.invoke(app, ["session-fork", "feature1"])
        assert result_fork.exit_code == 0
        assert "Forked new session 'feature1'" in result_fork.stdout
        # The forked view is written relative to the actual session root (project_dir), not the
        # CliRunner nested working directory (td).
        assert (project_dir / ".aico" / "sessions" / "feature1.json").is_file()

        # THEN session-list shows new active branch
        result_list2 = runner.invoke(app, ["session-list"])
        assert result_list2.exit_code == 0
        assert "feature1 (active)" in result_list2.stdout

        # WHEN switching back to main
        result_switch = runner.invoke(app, ["session-switch", "main"])
        assert result_switch.exit_code == 0
        assert "Switched active session to: main" in result_switch.stdout

        # THEN session-list shows main active again
        result_list3 = runner.invoke(app, ["session-list"])
        assert result_list3.exit_code == 0
        assert "main (active)" in result_list3.stdout
