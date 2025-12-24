# pyright: standard

import os
from datetime import UTC, datetime
from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.main import app
from tests import helpers

runner = CliRunner()


def find_msg(messages, snippet):
    """Robustly find a message in the prompt payload containing a snippet."""
    for m in messages:
        if snippet in m["content"]:
            return m
    return None


def patch_dt(mocker, ts):
    """
    Safely patch datetime.now in both module namespaces while preserving
    other essential class methods like fromisoformat.
    """
    dt_obj = datetime.fromtimestamp(ts, UTC)
    for target in ["aico.commands.prompt.datetime", "aico.llm.executor.datetime"]:
        mock = mocker.Mock(wraps=datetime)
        mock.now.return_value = dt_obj
        mock.fromisoformat = datetime.fromisoformat
        mocker.patch(target, mock)


def test_static_context_baseline(tmp_path: Path, mocker: MockerFixture) -> None:
    """Verifies that files modified before the window start are categorized as Static/Baseline."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td_str:
        td = Path(td_str)
        app_py = td / "app.py"
        app_py.write_text("baseline content")
        os.utime(app_py, (1000, 1000))  # Fixed past timestamp

        assert runner.invoke(app, ["init", "--model", "openai/test-model"]).exit_code == 0
        assert runner.invoke(app, ["add", "app.py"]).exit_code == 0

        patch_dt(mocker, 2000)
        mock_completion, _ = helpers.setup_test_session_and_llm(runner, app, td, mocker, "resp")

        assert runner.invoke(app, ["ask", "prompt"]).exit_code == 0

        messages = mock_completion.call_args.kwargs["messages"]
        static_block = find_msg(messages, "baseline contents")
        assert static_block is not None
        assert "baseline content" in static_block["content"]
        assert find_msg(messages, "UPDATED CONTEXT") is None


def test_floating_context_splicing(tmp_path: Path, mocker: MockerFixture) -> None:
    """Verifies that updates are categorized as Floating and spliced chronologically between messages."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td_str:
        td = Path(td_str)
        app_py = td / "app.py"
        app_py.write_text("v1")
        os.utime(app_py, (1000, 1000))

        assert runner.invoke(app, ["init", "--model", "openai/test-model"]).exit_code == 0
        assert runner.invoke(app, ["add", "app.py"]).exit_code == 0

        mock_completion, _ = helpers.setup_test_session_and_llm(runner, app, td, mocker, "r1")
        mock_completion.side_effect = [
            iter([helpers.create_mock_stream_chunk("r1", mocker)]),
            iter([helpers.create_mock_stream_chunk("r2", mocker)]),
        ]

        # Turn 1: Establish horizon at T=2000
        patch_dt(mocker, 2000)
        assert runner.invoke(app, ["ask", "p1"]).exit_code == 0

        # Turn 2: Update file at T=3000 (Floating relative to p1)
        app_py.write_text("v2")
        os.utime(app_py, (3000, 3000))

        # Turn 2: Second Prompt at T=4000
        patch_dt(mocker, 4000)
        assert runner.invoke(app, ["ask", "p2"]).exit_code == 0

        # Verify second call
        assert mock_completion.call_count == 2
        messages = mock_completion.call_args_list[1].kwargs["messages"]

        idx_p1 = next(i for i, m in enumerate(messages) if "p1" in m["content"])
        idx_floating = next(i for i, m in enumerate(messages) if "UPDATED CONTEXT" in m["content"])
        idx_p2 = next(i for i, m in enumerate(messages) if "p2" in m["content"])

        assert idx_p1 < idx_floating < idx_p2
        assert "v2" in messages[idx_floating]["content"]


def test_shifting_horizon(tmp_path: Path, mocker: MockerFixture) -> None:
    """Verifies that moving the history window promotes files from Floating to Static."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td_str:
        td = Path(td_str)
        app_py = td / "app.py"
        app_py.write_text("v1")
        os.utime(app_py, (1000, 1000))

        assert runner.invoke(app, ["init", "--model", "openai/test-model"]).exit_code == 0
        assert runner.invoke(app, ["add", "app.py"]).exit_code == 0

        mock_completion, _ = helpers.setup_test_session_and_llm(runner, app, td, mocker, "r1")
        mock_completion.side_effect = [
            iter([helpers.create_mock_stream_chunk("r1", mocker)]),
            iter([helpers.create_mock_stream_chunk("r2", mocker)]),
        ]

        patch_dt(mocker, 2000)
        assert runner.invoke(app, ["ask", "p1"]).exit_code == 0

        # File modified at T=3000
        app_py.write_text("v2")
        os.utime(app_py, (3000, 3000))

        # Shift window start
        assert runner.invoke(app, ["set-history", "1"]).exit_code == 0

        # Turn 2: Second Prompt at T=4000
        patch_dt(mocker, 4000)
        assert runner.invoke(app, ["ask", "p2"]).exit_code == 0

        messages = mock_completion.call_args_list[1].kwargs["messages"]

        # File (3000) is now older than window start (4000).
        msg_static = find_msg(messages, "baseline contents")
        assert msg_static is not None
        assert "v2" in msg_static["content"]
        assert find_msg(messages, "UPDATED CONTEXT") is None


def test_multiple_updates_synchronization(tmp_path: Path, mocker: MockerFixture) -> None:
    """Verifies multiple file changes are bundled into a single block based on max(mtime)."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td_str:
        td = Path(td_str)
        a = td / "a.py"
        a.write_text("a1")
        b = td / "b.py"
        b.write_text("b1")
        os.utime(a, (1000, 1000))
        os.utime(b, (1000, 1000))

        assert runner.invoke(app, ["init", "--model", "openai/test-model"]).exit_code == 0
        assert runner.invoke(app, ["add", "a.py", "b.py"]).exit_code == 0

        mock_completion, _ = helpers.setup_test_session_and_llm(runner, app, td, mocker, "r1")
        mock_completion.side_effect = [
            iter([helpers.create_mock_stream_chunk("r1", mocker)]),
            iter([helpers.create_mock_stream_chunk("r2", mocker)]),
            iter([helpers.create_mock_stream_chunk("r3", mocker)]),
        ]

        patch_dt(mocker, 2000)
        assert runner.invoke(app, ["ask", "p1"]).exit_code == 0

        # Updates
        a.write_text("a2")
        os.utime(a, (2500, 2500))
        b.write_text("b2")
        os.utime(b, (3000, 3000))

        patch_dt(mocker, 4000)
        assert runner.invoke(app, ["ask", "p2"]).exit_code == 0

        patch_dt(mocker, 5000)
        assert runner.invoke(app, ["ask", "p3"]).exit_code == 0

        messages = mock_completion.call_args_list[2].kwargs["messages"]

        idx_r1 = next(i for i, m in enumerate(messages) if "r1" in m["content"])
        idx_floating = next(i for i, m in enumerate(messages) if "UPDATED CONTEXT" in m["content"])
        idx_p2 = next(i for i, m in enumerate(messages) if "p2" in m["content"])

        assert idx_r1 < idx_floating < idx_p2
        assert "a2" in messages[idx_floating]["content"]
        assert "b2" in messages[idx_floating]["content"]


def test_fresh_session_baseline(tmp_path: Path, mocker: MockerFixture) -> None:
    """Verifies that files in a new session (no history) are treated as baseline."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td_str:
        td = Path(td_str)
        app_py = td / "app.py"
        app_py.write_text("fresh content")
        # Time doesn't strictly matter here as mtime < Year 3000

        assert runner.invoke(app, ["init", "--model", "openai/test-model"]).exit_code == 0
        assert runner.invoke(app, ["add", "app.py"]).exit_code == 0

        # T=Now: The very first prompt
        patch_dt(mocker, 1000000000)
        mock_completion, _ = helpers.setup_test_session_and_llm(runner, app, td, mocker, "r1")

        assert runner.invoke(app, ["ask", "p1"]).exit_code == 0

        # Verify: All files move to Static because history_to_use is empty when calculating horizon
        messages = mock_completion.call_args.kwargs["messages"]
        msg_static = find_msg(messages, "baseline contents")
        assert msg_static and "fresh content" in msg_static["content"]
        assert find_msg(messages, "UPDATED CONTEXT") is None
