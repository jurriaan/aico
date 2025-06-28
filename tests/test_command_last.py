# pyright: standard

import json
from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.main import app
from aico.utils import SESSION_FILE_NAME

runner = CliRunner()


def test_last_for_conversational_response(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session file with a conversational last_response
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        assistant_message = {
            "role": "assistant",
            "content": "Hello there!",
            "mode": "conversation",
            "model": "test-model",
            "timestamp": "...",
            "duration_ms": 123,
            "derived": None,
        }
        session_data = {
            "model": "test-model",
            "context_files": [],
            "chat_history": [assistant_message],
            "history_start_index": 0,
        }
        (Path(td) / SESSION_FILE_NAME).write_text(json.dumps(session_data))

        # WHEN run in a TTY (default)
        mocker.patch("aico.commands.last.is_terminal", return_value=True)
        result_tty = runner.invoke(app, ["last"])
        # THEN it shows the rich display content
        assert result_tty.exit_code == 0
        assert "Hello there!" in result_tty.stdout

        # WHEN run in a TTY with --recompute
        result_recompute_tty = runner.invoke(app, ["last", "--recompute"])
        # THEN it shows the same (recomputed) content
        assert result_recompute_tty.exit_code == 0
        assert "Hello there!" in result_recompute_tty.stdout

        # WHEN piped (default)
        mocker.patch("aico.commands.last.is_terminal", return_value=False)
        result_piped = runner.invoke(app, ["last"])
        # THEN it shows the display_content (since there's no diff)
        assert result_piped.exit_code == 0
        assert result_piped.stdout == "Hello there!"

        # WHEN piped with --recompute
        result_recompute_piped = runner.invoke(app, ["last", "--recompute"])
        # THEN it shows the same (recomputed) content
        assert result_recompute_piped.exit_code == 0
        assert result_recompute_piped.stdout == "Hello there!"


def test_last_for_diff_response_with_and_without_recompute(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session with a last_response, where the file on disk has changed since
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # This stored response was generated when file.py contained "old line"
        assistant_message = {
            "role": "assistant",
            "content": "File: file.py\n<<<<<<< SEARCH\nold line\n=======\nnew line\n>>>>>>> REPLACE",
            "mode": "diff",
            "model": "test-model",
            "timestamp": "2024-05-18T12:00:00Z",
            "duration_ms": 100,
            "derived": {
                "unified_diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old line\n+new line\n",
                "display_content": "File: file.py\n```diff\n--- a/file.py\n"
                + "+++ b/file.py\n@@ -1 +1 @@\n-old line\n+new line\n```\n",
            },
        }

        # NOTE: We can use a simpler session data structure for this test, since it's testing the `last` command,
        # not the `prompt` command's full flow.
        session_data = {
            "model": "test-model",
            "context_files": ["file.py"],
            "chat_history": [assistant_message],
            "history_start_index": 0,
        }
        session_file = Path(td) / SESSION_FILE_NAME
        session_file.write_text(json.dumps(session_data))

        # AND the file on disk has different content now
        file_on_disk = Path(td) / "file.py"
        file_on_disk.write_text("the content has now changed")

        # --- Test 1: Piped output ---
        mocker.patch("aico.commands.last.is_terminal", return_value=False)

        # WHEN piped without recompute
        result_stored_piped = runner.invoke(app, ["last"])
        # THEN it shows the original, stored unified diff, ignoring disk changes
        assert result_stored_piped.exit_code == 0
        assert result_stored_piped.stdout == assistant_message["derived"]["unified_diff"]

        # WHEN piped with recompute
        result_recomputed_piped = runner.invoke(app, ["last", "--recompute"])
        # THEN it recalculates the diff, which should now fail to apply.
        # The specific content of the failure message is tested in `test_diffing.py`.
        assert result_recomputed_piped.exit_code == 0
        assert "patch failed" in result_recomputed_piped.stdout

        # --- Test 2: TTY output ---
        mocker.patch("aico.commands.last.is_terminal", return_value=True)

        # WHEN TTY without recompute
        result_stored_tty = runner.invoke(app, ["last"])
        # THEN it shows the stored, pretty display_content
        assert result_stored_tty.exit_code == 0
        assert "new line" in result_stored_tty.stdout
        assert "patch failed" not in result_stored_tty.stdout

        # WHEN TTY with recompute
        result_recomputed_tty = runner.invoke(app, ["last", "--recompute"])
        # THEN it recalculates and shows a pretty "patch failed" error.
        assert result_recomputed_tty.exit_code == 0
        assert "patch failed" in result_recomputed_tty.stdout


def test_last_verbatim_flag(tmp_path: Path, mocker: MockerFixture) -> None:
    # GIVEN a session with a diff-containing response
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        assistant_message = {
            "role": "assistant",
            "content": "File: file.py\n<<<<<<< SEARCH\nold line\n=======\nnew line\n>>>>>>> REPLACE",
            "mode": "diff",
            "model": "test-model",
            "timestamp": "2024-05-18T12:00:00Z",
            "duration_ms": 100,
            "derived": {"unified_diff": "...", "display_content": "..."},
        }
        session_data = {
            "model": "test-model",
            "context_files": [],
            "chat_history": [assistant_message],
            "history_start_index": 0,
        }
        (Path(td) / SESSION_FILE_NAME).write_text(json.dumps(session_data))

        # WHEN running with --verbatim in a TTY
        mocker.patch("aico.commands.last.is_terminal", return_value=True)
        result_tty = runner.invoke(app, ["last", "--verbatim"])
        # THEN the raw response is shown, rendered as markdown
        assert result_tty.exit_code == 0
        assert "<<<<<<< SEARCH" in result_tty.stdout

        # WHEN running with --verbatim and piped
        mocker.patch("aico.commands.last.is_terminal", return_value=False)
        result_piped = runner.invoke(app, ["last", "--verbatim"])
        # THEN the raw content is printed without modification
        assert result_piped.exit_code == 0
        assert result_piped.stdout == assistant_message["content"]


def test_last_fails_when_no_assistant_response_exists(tmp_path: Path) -> None:
    # GIVEN a session file with no assistant messages in history
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN `aico last` is run
        result = runner.invoke(app, ["last"])

        # THEN the command fails with an error
        assert result.exit_code == 1
        assert "Error: Assistant response at index 1 not found." in result.stderr


def test_last_can_select_historical_message_with_n(tmp_path: Path) -> None:
    # GIVEN a session with two assistant messages in history
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        assistant_message_1 = {  # This will be the second-to-last
            "role": "assistant",
            "content": "response one",
            "mode": "conversation",
            "model": "test",
            "timestamp": "...",
            "duration_ms": 1,
            "derived": None,
        }
        assistant_message_2 = {  # This is the last
            "role": "assistant",
            "content": "response two",
            "mode": "conversation",
            "model": "test",
            "timestamp": "...",
            "duration_ms": 1,
            "derived": None,
        }
        session_data = {
            "model": "test-model",
            "context_files": [],
            "history_start_index": 0,
            "chat_history": [
                {"role": "user", "content": "p1", "mode": "conversation", "timestamp": "..."},
                assistant_message_1,
                {"role": "user", "content": "p2", "mode": "conversation", "timestamp": "..."},
                assistant_message_2,
            ],
        }
        (Path(td) / SESSION_FILE_NAME).write_text(json.dumps(session_data))

        # WHEN `aico last 2` is run
        result_2 = runner.invoke(app, ["last", "2"])

        # THEN it shows the content from the first assistant response
        assert result_2.exit_code == 0
        assert "response one" in result_2.stdout
        assert "response two" not in result_2.stdout

        # WHEN `aico last` (defaulting to n=1) is run
        result_1 = runner.invoke(app, ["last"])

        # THEN it shows the content from the second (last) assistant response
        assert result_1.exit_code == 0
        assert "response two" in result_1.stdout
        assert "response one" not in result_1.stdout


def test_last_fails_with_out_of_bounds_n(tmp_path: Path) -> None:
    # GIVEN a session with one assistant message
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        assistant_message = {
            "role": "assistant",
            "content": "only response",
            "mode": "conversation",
            "model": "test",
            "timestamp": "...",
            "duration_ms": 1,
            "derived": None,
        }
        session_data = {
            "model": "test-model",
            "context_files": [],
            "history_start_index": 0,
            "chat_history": [assistant_message],
        }
        (Path(td) / SESSION_FILE_NAME).write_text(json.dumps(session_data))

        # WHEN `aico last 2` is run
        result = runner.invoke(app, ["last", "2"])

        # THEN it fails with a clear error message
        assert result.exit_code == 1
        assert "Error: Assistant response at index 2 not found." in result.stderr


def test_last_fails_with_invalid_n_cli_arg(tmp_path: Path) -> None:
    # GIVEN a session file
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN `aico last` is run with an invalid N (less than 1)
        result = runner.invoke(app, ["last", "0"])

        # THEN typer's argument validation handles it
        assert result.exit_code != 0
        assert "Invalid value for '[N]': 0 is not in the range x>=1" in result.stderr
