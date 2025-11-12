# pyright: standard

import json
from pathlib import Path

from typer.testing import CliRunner

from aico.main import app

runner = CliRunner()


def test_session_fork_creates_new_view_and_switches(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # GIVEN a shared-history project
        result_init = runner.invoke(app, ["init"])
        assert result_init.exit_code == 0

        # WHEN I fork a new session
        result_fork = runner.invoke(app, ["session-fork", "forked"])
        # THEN it succeeds, creates a new view, and switches to it
        assert result_fork.exit_code == 0
        assert "Forked new session 'forked' and switched to it." in result_fork.stdout

        # AND the pointer points to the new view
        pointer_file = Path(td) / ".ai_session.json"
        pointer_data = json.loads(pointer_file.read_text())
        assert pointer_data["path"] == ".aico/sessions/forked.json"

        # AND the new session view exists
        view_file = Path(td) / ".aico" / "sessions" / "forked.json"
        assert view_file.is_file()


def test_session_fork_fails_if_name_exists(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # GIVEN a shared-history project
        result_init = runner.invoke(app, ["init"])
        assert result_init.exit_code == 0

        # AND a session named 'existing' already exists
        sessions_dir = Path(td) / ".aico" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "existing.json").write_text(
            '{"model":"m","context_files":[],"message_indices":[],"history_start_pair":0,"excluded_pairs":[]}'
        )

        # WHEN I try to fork with the same name
        result = runner.invoke(app, ["session-fork", "existing"])

        # THEN the command fails
        assert result.exit_code == 1
        assert "Error: A session view named 'existing' already exists." in result.stderr


def test_session_fork_with_until_pair_out_of_range(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # GIVEN a shared-history project with no message pairs
        result_init = runner.invoke(app, ["init"])
        assert result_init.exit_code == 0

        # WHEN I pass an out-of-range --until-pair
        result = runner.invoke(app, ["session-fork", "new-fork", "--until-pair", "0"])

        # THEN the command fails with an out-of-range error
        assert result.exit_code == 1
        assert "out of range" in result.stderr
