# pyright: standard

import json
from pathlib import Path

from typer.testing import CliRunner

from aico.lib.models import SessionData
from aico.lib.session import SESSION_FILE_NAME, save_session
from aico.main import app

runner = CliRunner()


def test_dump_context_outputs_sorted_json(tmp_path: Path) -> None:
    """
    Tests that `aico dump-context` correctly outputs a sorted list
    of context files in JSON format.
    """
    # GIVEN a session with an unsorted list of context files
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        session_data = SessionData(
            model="test-model",
            context_files=["src/file2.ts", "file1.py", "README.md"],
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # WHEN I run `aico dump-context`
        result = runner.invoke(app, ["dump-context"])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the output is a JSON object with the sorted context files
        output_data = json.loads(result.stdout)
        expected_data = {"context_files": ["README.md", "file1.py", "src/file2.ts"]}
        assert output_data == expected_data


def test_dump_context_with_empty_context(tmp_path: Path) -> None:
    """
    Tests that `aico dump-context` handles an empty context list correctly.
    """
    # GIVEN a session with an empty context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_dir = Path(td)
        session_data = SessionData(
            model="test-model",
            context_files=[],
        )
        save_session(session_dir / SESSION_FILE_NAME, session_data)

        # WHEN I run `aico dump-context`
        result = runner.invoke(app, ["dump-context"])

        # THEN the command succeeds
        assert result.exit_code == 0

        # AND the output is a JSON object with an empty list
        output_data = json.loads(result.stdout)
        expected_data = {"context_files": []}
        assert output_data == expected_data
