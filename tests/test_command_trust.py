# pyright: standard
from pathlib import Path

import typer
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.commands.trust import trust

runner = CliRunner()
app = typer.Typer()
app.command()(trust)


def test_trust_command_cwd(tmp_path: Path, mocker: MockerFixture) -> None:
    # Mock core logic to avoid side effects on actual config
    mock_trust = mocker.patch("aico.commands.trust.trust_project")
    mocker.patch("aico.commands.trust.is_project_trusted", side_effect=[False, True])

    # GIVEN current working dir is tmp_path
    with runner.isolated_filesystem(temp_dir=tmp_path):
        cwd = Path.cwd().resolve()

        # WHEN running 'trust'
        result = runner.invoke(app, [])

        # THEN calls trust_project with CWD
        assert result.exit_code == 0
        mock_trust.assert_called_with(cwd)
        assert "Success: Trusted project" in result.stdout


def test_trust_command_revoke(tmp_path: Path, mocker: MockerFixture) -> None:
    mock_untrust = mocker.patch("aico.commands.trust.untrust_project", return_value=True)

    with runner.isolated_filesystem(temp_dir=tmp_path):
        cwd = Path.cwd().resolve()
        result = runner.invoke(app, ["--revoke"])

        assert result.exit_code == 0
        mock_untrust.assert_called_with(cwd)
        assert "Revoked trust" in result.stdout


def test_trust_command_list(mocker: MockerFixture) -> None:
    mocker.patch("aico.commands.trust.list_trusted_projects", return_value=["/a/b", "/c/d"])
    result = runner.invoke(app, ["--list"])

    assert result.exit_code == 0
    assert "- /a/b" in result.stdout
    assert "- /c/d" in result.stdout
