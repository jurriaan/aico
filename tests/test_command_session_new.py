# pyright: standard

import json
from pathlib import Path

from typer.testing import CliRunner

from aico.main import app

runner = CliRunner()


def test_session_new_creates_empty_session_and_switches(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # GIVEN a shared-history project (initialize main session)
        init_result = runner.invoke(app, ["init", "--model", "original-model"])
        assert init_result.exit_code == 0

        # WHEN I run `aico session-new clean-slate`
        result = runner.invoke(app, ["session-new", "clean-slate"])

        # THEN the command succeeds
        assert result.exit_code == 0
        assert "Created new empty session 'clean-slate'" in result.stdout
        assert "switched to it" in result.stdout

        # AND the pointer now references the new view
        pointer_file = Path(td) / ".ai_session.json"
        pointer_data = json.loads(pointer_file.read_text())
        assert pointer_data["path"] == ".aico/sessions/clean-slate.json"

        # AND the new session view exists and is empty
        view_file = Path(td) / ".aico" / "sessions" / "clean-slate.json"
        assert view_file.is_file()
        view_data = json.loads(view_file.read_text())
        assert view_data["context_files"] == []
        assert view_data["message_indices"] == []
        assert view_data["history_start_pair"] == 0
        assert view_data["excluded_pairs"] == []

        # AND it inherits the model from the previous session
        assert view_data["model"] == "original-model"


def test_session_new_with_model_override(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # GIVEN a shared-history project
        init_result = runner.invoke(app, ["init", "--model", "original-model"])
        assert init_result.exit_code == 0

        # WHEN I run `aico session-new new-model-session --model override-model`
        result = runner.invoke(app, ["session-new", "new-model-session", "--model", "override-model"])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the new session view uses the specified model
        view_file = Path(td) / ".aico" / "sessions" / "new-model-session.json"
        assert view_file.is_file()
        view_data = json.loads(view_file.read_text())
        assert view_data["model"] == "override-model"
        assert "with model 'override-model'" in result.stdout


def test_session_new_fails_if_session_exists(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # GIVEN a shared-history project
        init_result = runner.invoke(app, ["init"])
        assert init_result.exit_code == 0

        # AND a session named 'existing' already exists
        sessions_dir = Path(td) / ".aico" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "existing.json").write_text(
            '{"model":"m","context_files":[],"message_indices":[],"history_start_pair":0,"excluded_pairs":[]}'
        )

        # WHEN I try to create a new session with the same name
        result = runner.invoke(app, ["session-new", "existing"])

        # THEN the command fails
        assert result.exit_code == 1
        assert "Error: A session view named 'existing' already exists." in result.stderr


def test_session_new_fails_in_legacy_session(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # GIVEN a legacy (single-file) session
        legacy_session_file = Path(td) / ".ai_session.json"
        legacy_session_file.write_text(json.dumps({"model": "test-model", "chat_history": []}))

        # WHEN I run `aico session-new wont-work`
        result = runner.invoke(app, ["session-new", "wont-work"])

        # THEN the command fails because it's not a shared-history session
        assert result.exit_code == 1
        assert "This command requires a shared-history session." in result.stderr
