# pyright: standard

import json
import sys
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


def test_session_fork_ephemeral_execution(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # GIVEN a shared-history project
        runner.invoke(app, ["init"])

        # WHEN I run a command in an ephemeral fork (name provided + --ephemeral)
        # We use a python script to inspect the environment variable AICO_SESSION_FILE
        # and the content of the pointer it references.
        inner_script = "\n".join(
            [
                "import os, json; ",
                "ptr_path = os.environ['AICO_SESSION_FILE']; ",
                "with open(ptr_path) as f: data = json.load(f); ",
                "view_path = data['path']; ",
                "with open('evidence.txt', 'w') as f: f.write(f'{ptr_path}\\n{view_path}')",
            ]
        )

        result = runner.invoke(
            app, ["session-fork", "temp-job", "--ephemeral", "--", sys.executable, "-c", inner_script]
        )

        print(result.stderr, file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        assert result.exit_code == 0

        # THEN the evidence file should contain paths
        evidence = Path("evidence.txt")
        assert evidence.exists()
        lines = evidence.read_text().splitlines()
        ptr_path_used = Path(lines[0])
        view_rel_path = Path(lines[1])

        # AND the pointer file should have been cleaned up
        assert not ptr_path_used.exists()

        # AND the ephemeral view file (referenced by the pointer) should have been cleaned up
        # Note: view_rel_path is relative to ptr_path's parent (project root)
        view_path_used = (ptr_path_used.parent / view_rel_path).resolve()
        assert not view_path_used.exists()
        assert "temp-job.json" in str(view_path_used)


def test_session_fork_persistent_execution(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # GIVEN a shared-history project
        runner.invoke(app, ["init"])

        # WHEN I run a command in a NAMED fork
        inner_script = "print('running inside fork')"
        result = runner.invoke(app, ["session-fork", "my-exec-fork", "--", sys.executable, "-c", inner_script])

        assert result.exit_code == 0

        # THEN the view file for that fork SHOULD exist (not cleaned up)
        view_file = Path(td) / ".aico" / "sessions" / "my-exec-fork.json"
        assert view_file.exists()

        # AND the main session pointer should NOT have switched (execution is isolated)
        main_pointer = Path(td) / ".ai_session.json"
        pointer_data = json.loads(main_pointer.read_text())
        assert "my-exec-fork" not in pointer_data["path"]
