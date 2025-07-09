# pyright: standard


from typer.testing import CliRunner

from aico.main import app

runner = CliRunner()


def test_no_command_shows_help() -> None:
    # GIVEN the app
    # WHEN `aico` is run with no command
    result = runner.invoke(app, [])

    # THEN the command succeeds and shows the help text with the flat command structure
    assert result.exit_code == 0
    assert "Usage: root [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert " status " in result.stdout
    assert " log " in result.stdout
    assert " set-history " in result.stdout
    assert " tokens " in result.stdout
    assert " ask " in result.stdout
    assert " generate-patch | gen " in result.stdout
    assert " init " in result.stdout
    assert " add " in result.stdout
    assert " last " in result.stdout
    assert " drop " in result.stdout
    assert " prompt " in result.stdout
    # Check that 'history' is not a top-level command, avoiding matches in help text.
    assert "│ history " not in result.stdout
