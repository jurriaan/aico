# pyright: standard

import json
from pathlib import Path

from typer.testing import CliRunner

from aico.main import app

runner = CliRunner()


def test_session_switch_switches_active_pointer(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # GIVEN a shared-history project with a second session
        result_init = runner.invoke(app, ["init"])
        assert result_init.exit_code == 0

        result_new = runner.invoke(app, ["session-new", "feature"])
        assert result_new.exit_code == 0

        pointer_file = Path(td) / ".ai_session.json"
        pointer_data = json.loads(pointer_file.read_text())
        assert pointer_data["path"] == ".aico/sessions/feature.json"

        # WHEN I switch back to main
        result_switch_main = runner.invoke(app, ["session-switch", "main"])
        # THEN the pointer updates and a success message is printed
        assert result_switch_main.exit_code == 0
        assert "Switched active session to: main" in result_switch_main.stdout
        pointer_data = json.loads(pointer_file.read_text())
        assert pointer_data["path"] == ".aico/sessions/main.json"

        # WHEN I switch to feature again
        result_switch_feature = runner.invoke(app, ["session-switch", "feature"])
        # THEN the pointer updates and a success message is printed
        assert result_switch_feature.exit_code == 0
        assert "Switched active session to: feature" in result_switch_feature.stdout
        pointer_data = json.loads(pointer_file.read_text())
        assert pointer_data["path"] == ".aico/sessions/feature.json"


def test_session_switch_fails_for_missing_view(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # GIVEN a project with only the default 'main' view
        result_init = runner.invoke(app, ["init"])
        assert result_init.exit_code == 0

        # WHEN I try to switch to a non-existent view
        result = runner.invoke(app, ["session-switch", "nope"])

        # THEN the command fails with a clear error
        assert result.exit_code == 1
        assert "Error: Session view 'nope' not found at" in result.stderr
