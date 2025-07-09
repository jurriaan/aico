# pyright: standard

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.main import app
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


@pytest.fixture
def session_with_two_pairs(tmp_path: Path) -> Iterator[Path]:
    """Creates a session with two user/assistant pairs within an isolated filesystem."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        session_data = {
            "model": "test-model",
            "context_files": [],
            "history_start_index": 0,
            "chat_history": [
                {"role": "user", "content": "prompt one", "mode": "conversation", "timestamp": "t1"},
                {
                    "role": "assistant",
                    "content": "response one",
                    "mode": "conversation",
                    "model": "test",
                    "timestamp": "t1",
                    "duration_ms": 1,
                },
                {"role": "user", "content": "prompt two", "mode": "conversation", "timestamp": "t2"},
                {
                    "role": "assistant",
                    "content": "response two",
                    "mode": "conversation",
                    "model": "test",
                    "timestamp": "t2",
                    "duration_ms": 1,
                },
            ],
        }
        (Path(td) / SESSION_FILE_NAME).write_text(json.dumps(session_data))
        # Yielding here ensures the 'with' block remains active for the test's duration
        yield Path(td)


def test_last_default_shows_last_assistant_response(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last` is run with no arguments
    result = runner.invoke(app, ["last"])

    # THEN it shows the assistant response from the last pair (-1)
    assert result.exit_code == 0
    assert "response two" in result.stdout
    assert "response one" not in result.stdout


def test_last_can_select_pair_by_positive_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last 0` is run
    result = runner.invoke(app, ["last", "0"])

    # THEN it shows the assistant response from the first pair (index 0)
    assert result.exit_code == 0
    assert "response one" in result.stdout
    assert "response two" not in result.stdout


def test_last_can_select_pair_by_negative_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last -2` is run
    result = runner.invoke(app, ["last", "-2"])

    # THEN it shows the assistant response from the first pair (index -2)
    assert result.exit_code == 0
    assert "response one" in result.stdout
    assert "response two" not in result.stdout


def test_last_prompt_flag_shows_user_prompt(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last -1 --prompt` is run
    result = runner.invoke(app, ["last", "-1", "--prompt"])

    # THEN it shows the user prompt from the last pair
    assert result.exit_code == 0
    assert "prompt two" in result.stdout
    assert "response two" not in result.stdout

    # WHEN `aico last 0 --prompt` is run
    result_0 = runner.invoke(app, ["last", "0", "--prompt"])

    # THEN it shows the user prompt from the first pair
    assert result_0.exit_code == 0
    assert "prompt one" in result_0.stdout
    assert "response one" not in result_0.stdout


def test_last_verbatim_flag_for_prompt(session_with_two_pairs: Path, mocker: MockerFixture) -> None:
    # GIVEN a session
    # WHEN running with --verbatim and --prompt (piped, so no rich rendering)
    mocker.patch("aico.commands.last.is_terminal", return_value=False)
    result = runner.invoke(app, ["last", "-1", "--prompt", "--verbatim"])

    # THEN the raw prompt content is printed without modification
    assert result.exit_code == 0
    assert result.stdout == "prompt two"


def test_last_fails_when_no_pairs_exist(tmp_path: Path) -> None:
    # GIVEN a session file with no message pairs
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN `aico last` is run
        result = runner.invoke(app, ["last"])

        # THEN the command fails with a clear error
        assert result.exit_code == 1
        assert "Error: No message pairs found in history." in result.stderr


@pytest.mark.parametrize("invalid_index", ["99", "-99"])
def test_last_fails_with_out_of_bounds_index(session_with_two_pairs: Path, invalid_index: str) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last` is run with an out-of-bounds index
    result = runner.invoke(app, ["last", invalid_index])

    # THEN it fails with a clear error message
    assert result.exit_code == 1
    assert f"Error: Pair at index {invalid_index} not found. Valid indices are 0 to 1 (or -1 to -2)." in result.stderr


def test_last_fails_with_invalid_index_format(session_with_two_pairs: Path) -> None:
    # GIVEN a session file
    # WHEN `aico last` is run with a non-integer index
    result = runner.invoke(app, ["last", "abc"])

    # THEN it fails with a parsing error
    assert result.exit_code == 1
    assert "Error: Invalid index 'abc'. Must be an integer." in result.stderr


def test_last_recompute_fails_with_prompt_flag(session_with_two_pairs: Path) -> None:
    # GIVEN a session
    # WHEN `aico last` is run with both --recompute and --prompt
    result = runner.invoke(app, ["last", "-1", "--prompt", "--recompute"])

    # THEN it fails with a specific error
    assert result.exit_code == 1
    assert "Error: --recompute cannot be used with --prompt." in result.stderr


def test_last_recompute_for_diff_response(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session with a diff response
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        user_message = {"role": "user", "content": "p1", "mode": "diff", "timestamp": "t1"}
        assistant_message = {
            "role": "assistant",
            "content": "File: file.py\n<<<<<<< SEARCH\nold line\n=======\nnew line\n>>>>>>> REPLACE",
            "mode": "diff",
            "model": "test-model",
            "timestamp": "t1",
            "duration_ms": 100,
            "derived": {
                "unified_diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old line\n+new line\n",
            },
        }

        session_data = {
            "model": "test-model",
            "context_files": ["file.py"],
            "chat_history": [user_message, assistant_message],
            "history_start_index": 0,
        }
        session_file = Path(td) / SESSION_FILE_NAME
        session_file.write_text(json.dumps(session_data))
        (Path(td) / "file.py").write_text("old line\n")
        mocker.patch("aico.commands.last.is_terminal", return_value=False)

        # WHEN piped with recompute
        result_recomputed_piped = runner.invoke(app, ["last", "0", "--recompute"])

        # THEN it recalculates the diff, which should succeed and be identical
        assert result_recomputed_piped.exit_code == 0
        assert result_recomputed_piped.stdout == assistant_message["derived"]["unified_diff"]
        assert "Warning" not in result_recomputed_piped.stderr
