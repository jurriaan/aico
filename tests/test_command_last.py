# pyright: standard

from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.consts import SESSION_FILE_NAME
from aico.historystore import (
    HistoryStore,
    SessionView,
    append_pair_to_view,
    save_view,
    switch_active_pointer,
)
from aico.historystore.models import HistoryRecord
from aico.main import app
from aico.models import AssistantChatMessage, DerivedContent, Mode, SessionData, UserChatMessage
from tests.helpers import save_session

runner = CliRunner()


def test_last_default_shows_last_assistant_response(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last` is run with no arguments
    result = runner.invoke(app, ["last"])

    # THEN it shows the assistant response from the last pair (-1)
    assert result.exit_code == 0
    assert "assistant response 1" in result.stdout
    assert "assistant response 0" not in result.stdout


def test_last_can_select_pair_by_positive_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last 0` is run
    result = runner.invoke(app, ["last", "0"])

    # THEN it shows the assistant response from the first pair (index 0)
    assert result.exit_code == 0
    assert "assistant response 0" in result.stdout
    assert "assistant response 1" not in result.stdout


def test_last_can_select_pair_by_negative_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last -2` is run
    result = runner.invoke(app, ["last", "-2"])

    # THEN it shows the assistant response from the first pair (index -2)
    assert result.exit_code == 0
    assert "assistant response 0" in result.stdout
    assert "assistant response 1" not in result.stdout


def test_last_prompt_flag_shows_user_prompt(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last -1 --prompt` is run
    result = runner.invoke(app, ["last", "-1", "--prompt"])

    # THEN it shows the user prompt from the last pair
    assert result.exit_code == 0
    assert "user prompt 1" in result.stdout
    assert "assistant response 1" not in result.stdout

    # WHEN `aico last 0 --prompt` is run
    result_0 = runner.invoke(app, ["last", "0", "--prompt"])

    # THEN it shows the user prompt from the first pair
    assert result_0.exit_code == 0
    assert "user prompt 0" in result_0.stdout
    assert "assistant response 0" not in result_0.stdout


def test_last_verbatim_flag_for_prompt(session_with_two_pairs: Path, mocker: MockerFixture) -> None:
    # GIVEN a session
    # WHEN running with --verbatim and --prompt (piped, so no rich rendering)
    mocker.patch("aico.commands.last.is_terminal", return_value=False)
    result = runner.invoke(app, ["last", "-1", "--prompt", "--verbatim"])

    # THEN the raw prompt content is printed without modification
    assert result.exit_code == 0
    assert result.stdout == "user prompt 1"


def test_last_json_output(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last --json` is run
    result = runner.invoke(app, ["last", "-1", "--json"])

    # THEN it should succeed and return valid JSON
    assert result.exit_code == 0

    # AND the JSON should be parseable and contain expected fields
    import json

    json_data = json.loads(result.stdout)

    # Check that we have the basic expected fields
    assert "pair_index" in json_data
    assert "user" in json_data
    assert "assistant" in json_data

    assert json_data["pair_index"] == 1
    assert json_data["user"]["role"] == "user"
    assert "user prompt 1" in json_data["user"]["content"]
    assert json_data["assistant"]["role"] == "assistant"
    assert "assistant response 1" in json_data["assistant"]["content"]

    # Ensure IDs are populated (not null) for shared-history sessions
    assert json_data["user"]["id"] is not None
    assert json_data["assistant"]["id"] is not None
    assert isinstance(json_data["user"]["id"], int)
    assert isinstance(json_data["assistant"]["id"], int)


def test_last_json_output_ignores_prompt_flag(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last --json --prompt` is run
    result = runner.invoke(app, ["last", "-1", "--json", "--prompt"])

    # THEN it should still output the full pair structure
    assert result.exit_code == 0

    import json

    json_data = json.loads(result.stdout)
    assert "user" in json_data
    assert "assistant" in json_data
    assert json_data["user"]["content"] == "user prompt 1"


def test_last_json_output_with_specific_index(session_with_two_pairs: Path) -> None:
    # GIVEN a session with two pairs
    # WHEN `aico last 0 --json` is run to get the first pair
    result = runner.invoke(app, ["last", "0", "--json"])

    # THEN it should succeed and return valid JSON
    assert result.exit_code == 0

    # AND the JSON should contain the content from the first pair
    import json

    json_data = json.loads(result.stdout)
    assert json_data["pair_index"] == 0
    assert "assistant response 0" in json_data["assistant"]["content"]
    assert "assistant response 1" not in json_data["assistant"]["content"]


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
    assert "Error: Index out of bounds." in result.stderr


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
        user_message = UserChatMessage(role="user", content="p1", mode=Mode.DIFF, timestamp="t1")
        assistant_message = AssistantChatMessage(
            role="assistant",
            content="File: file.py\n<<<<<<< SEARCH\nold line\n=======\nnew line\n>>>>>>> REPLACE",
            mode=Mode.DIFF,
            model="test-model",
            timestamp="t1",
            duration_ms=100,
            derived=DerivedContent(
                unified_diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old line\n+new line\n",
            ),
        )

        session_data = SessionData(
            model="test-model",
            context_files=["file.py"],
            chat_history=[user_message, assistant_message],
        )

        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        (Path(td) / "file.py").write_text("old line\n")
        mocker.patch("aico.commands.last.is_terminal", return_value=False)

        # WHEN piped with recompute
        result_recomputed_piped = runner.invoke(app, ["last", "0", "--recompute"])

        # THEN it recalculates the diff, which should succeed and be identical
        assert result_recomputed_piped.exit_code == 0
        assert (
            assistant_message.derived is not None
            and assistant_message.derived.unified_diff == result_recomputed_piped.stdout
        )
        assert "Warning" not in result_recomputed_piped.stderr


def test_last_can_access_pair_before_active_window(tmp_path: Path) -> None:
    # GIVEN a session with 3 pairs and an active window starting at pair 1
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = [
            UserChatMessage(role="user", content="prompt 0", mode=Mode.CONVERSATION, timestamp="t0"),
            AssistantChatMessage(
                role="assistant",
                content="response 0",
                mode=Mode.CONVERSATION,
                timestamp="t0",
                model="test",
                duration_ms=1,
            ),
            UserChatMessage(role="user", content="prompt 1", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(
                role="assistant",
                content="response 1",
                mode=Mode.CONVERSATION,
                timestamp="t1",
                model="test",
                duration_ms=1,
            ),
            UserChatMessage(role="user", content="prompt 2", mode=Mode.CONVERSATION, timestamp="t2"),
            AssistantChatMessage(
                role="assistant",
                content="response 2",
                mode=Mode.CONVERSATION,
                timestamp="t2",
                model="test",
                duration_ms=1,
            ),
        ]
        session_data = SessionData(
            model="test-model",
            context_files=[],
            history_start_pair=1,  # Active window starts at pair 1
            chat_history=history,
        )
        save_session(Path(td) / SESSION_FILE_NAME, session_data)

        # WHEN `aico last 0` is run, targeting a pair before the active window
        result = runner.invoke(app, ["last", "0"])

        # THEN it should succeed and show the response from the first pair (index 0)
        assert result.exit_code == 0
        assert "response 0" in result.stdout
        assert "response 1" not in result.stdout

        # WHEN `aico last -3` is run, which is equivalent to index 0
        result_neg = runner.invoke(app, ["last", "-3"])

        # THEN it should also succeed and show the response from the first pair
        assert result_neg.exit_code == 0
        assert "response 0" in result_neg.stdout


def test_last_can_access_pair_before_active_window_shared_history(tmp_path: Path) -> None:
    # GIVEN a shared-history session with 3 pairs and an active window starting at pair 1
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        project_root = Path(td)
        history_root = project_root / ".aico" / "history"
        sessions_dir = project_root / ".aico" / "sessions"
        history_root.mkdir(parents=True, exist_ok=True)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        store = HistoryStore(history_root)
        view = SessionView(
            model="test-model",
            context_files=[],
            message_indices=[],
            history_start_pair=1,  # Active window starts at pair 1
            excluded_pairs=[],
        )

        for i in range(3):
            user_record = HistoryRecord(
                role="user",
                content=f"prompt {i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
            )
            assistant_record = HistoryRecord(
                role="assistant",
                content=f"response {i}",
                mode=Mode.CONVERSATION,
                timestamp=f"t{i}",
                model="test-model",
                duration_ms=1,
            )
            _ = append_pair_to_view(store, view, user_record, assistant_record)

        view_path = sessions_dir / "main.json"
        save_view(view_path, view)
        session_file = project_root / SESSION_FILE_NAME
        switch_active_pointer(session_file, view_path)

        # WHEN `aico last 0` is run, targeting a pair before the active window
        result = runner.invoke(app, ["last", "0"])

        # THEN it should succeed and show the response from the first pair (index 0)
        assert result.exit_code == 0
        assert "response 0" in result.stdout
        assert "response 1" not in result.stdout

        # WHEN `aico last -3` is run, which is equivalent to index 0
        result_neg = runner.invoke(app, ["last", "-3"])

        # THEN it should also succeed and show the response from the first pair
        assert result_neg.exit_code == 0
        assert "response 0" in result_neg.stdout
