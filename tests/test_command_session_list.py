# pyright: standard

from pathlib import Path

from typer.testing import CliRunner

from aico.main import app

runner = CliRunner()


def test_session_list_shows_active_and_all_views(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # GIVEN a shared-history project with one default view
        result_init = runner.invoke(app, ["init"])
        assert result_init.exit_code == 0

        # WHEN I list sessions
        result_list_1 = runner.invoke(app, ["session-list"])
        # THEN it shows the default 'main' view as active
        assert result_list_1.exit_code == 0
        assert "Available sessions:" in result_list_1.stdout
        assert "  - main (active)" in result_list_1.stdout

        # WHEN I create a new session and list again
        result_new = runner.invoke(app, ["session-new", "dev"])
        assert result_new.exit_code == 0

        result_list_2 = runner.invoke(app, ["session-list"])
        # THEN both sessions are listed and 'dev' is active
        assert result_list_2.exit_code == 0
        assert "  - main" in result_list_2.stdout
        assert "  - dev (active)" in result_list_2.stdout
