# pyright: standard


from typer.testing import CliRunner

from aico.main import app

runner = CliRunner()


def test_no_command_shows_help() -> None:
    # GIVEN the app
    # WHEN `aico` is run with no command
    result = runner.invoke(app, [])

    # THEN the command succeeds and shows the help text
    assert result.exit_code == 0
    assert "Usage: root [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert " init" in result.stdout
    assert " add" in result.stdout
    assert " last" in result.stdout
    assert " drop" in result.stdout
    assert " prompt" in result.stdout
