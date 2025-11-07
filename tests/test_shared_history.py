# pyright: standard

import shlex
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

# historystore imports
from aico.historystore import (
    HistoryRecord,
    HistoryStore,
    SessionView,
    save_view,
    switch_active_pointer,
)
from aico.historystore.models import UserMetaEnvelope
from aico.lib.models import DerivedContent, Mode, TokenUsage, UserDerivedMeta

# aico imports
from aico.main import app

runner = CliRunner()


@pytest.fixture
def shared_history_project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Creates a temporary project directory with a shared-history session.

    This fixture sets up:
    - A `.aico` directory with a history store and sessions.
    - A root `.ai_session.json` pointer file.
    - Two files in the root.
    - A history store with two user/assistant pairs.
    - The first assistant response contains a diff in its derived content.

    It also changes the current working directory to this new project directory.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    history_root = project_dir / ".aico" / "history"
    sessions_dir = project_dir / ".aico" / "sessions"

    (project_dir / "file1.py").write_text("def func_one(): pass\n")
    (project_dir / "new_file.txt").write_text("hello")

    store = HistoryStore(history_root)
    # A diff for the first pair that aico can parse
    derived_content = DerivedContent(
        unified_diff="--- a/file1.py\n+++ b/file1.py\n@@ -1 +1 @@\n-def func_one(): pass"
        + "\n+def func_one(a: int): pass\n",
        display_content=[
            {
                "type": "diff",
                "content": "--- a/file1.py\n+++ b/file1.py\n@@ -1 +1 @@\n-def func_one(): pass"
                + "\n+def func_one(a: int): pass\n",
            }
        ],
    )
    u0_idx = store.append(HistoryRecord(role="user", content="prompt 0", mode=Mode.DIFF))
    a0_idx = store.append(
        HistoryRecord(
            role="assistant",
            content="resp 0 with diff",
            mode=Mode.DIFF,
            model="shared-hist-model",
            derived=derived_content,
        )
    )
    u1_idx = store.append(HistoryRecord(role="user", content="prompt 1", mode=Mode.CONVERSATION))
    a1_idx = store.append(
        HistoryRecord(
            role="assistant", content="resp 1 conversational", mode=Mode.CONVERSATION, model="shared-hist-model"
        )
    )

    view = SessionView(
        model="shared-hist-model",
        context_files=["file1.py"],
        message_indices=[u0_idx, a0_idx, u1_idx, a1_idx],
        excluded_pairs=[1],  # Exclude the last pair for 'redo' test
    )
    view_path = sessions_dir / "main.json"
    save_view(view_path, view)

    pointer_file = project_dir / ".ai_session.json"
    switch_active_pointer(pointer_file, view_path)

    return project_dir


def test_log_on_shared_session(shared_history_project_dir: Path) -> None:
    """Tests that `log` correctly displays history from a shared session."""
    result = runner.invoke(app, ["log"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Active Context Log" in result.stdout
    assert "prompt 0" in result.stdout
    assert "resp 0 with diff" in result.stdout
    assert "prompt 1" in result.stdout
    assert "resp 1 conversational" in result.stdout


def test_last_on_shared_session_conversational(shared_history_project_dir: Path) -> None:
    """Tests that `last` correctly displays conversational content from a shared session."""
    result = runner.invoke(app, ["last"], catch_exceptions=False)
    assert result.exit_code == 0
    assert result.stdout.strip() == "resp 1 conversational"


def test_last_on_shared_session_diff(shared_history_project_dir: Path) -> None:
    """Tests that `last` correctly displays a diff from derived content in a shared session."""
    result = runner.invoke(app, ["last", "-2"], catch_exceptions=False)
    assert result.exit_code == 0
    expected_diff = "--- a/file1.py\n+++ b/file1.py\n@@ -1 +1 @@\n-def func_one(): pass\n+def func_one(a: int): pass\n"
    assert result.stdout.strip() == expected_diff.strip()


@pytest.mark.parametrize(
    "command_str",
    [
        "ask 'a question'",
        "gen 'a change'",
        "prompt 'a raw prompt'",
        "add new_file.txt",
        "drop file1.py",
        "edit",  # Defaults to -1, avoids option parsing issue
        "undo 0",  # Test on a non-excluded pair to force a save
        "redo",  # Test on the excluded pair to force a save
        "set-history 0",
    ],
)
def test_mutating_commands_succeed_on_shared_session(
    shared_history_project_dir: Path, command_str: str, mocker: MockerFixture
) -> None:
    """Tests that all mutating commands succeed on a shared-history session."""
    args = shlex.split(command_str)
    command_name = args[0]

    if command_name in ["ask", "gen", "prompt"]:
        # For 'ask', 'gen', 'prompt': prevent real LLM calls which would fail due to the test model name.
        # Patch where it's used, not where it's defined.
        from aico.lib.models import InteractionResult

        mocker.patch(
            "aico.commands.prompt.execute_interaction",
            return_value=InteractionResult(
                content="mock response",
                display_items=[],
                token_usage=None,
                cost=None,
                duration_ms=0,
                unified_diff=None,
            ),
        )

    if command_name == "edit":
        # For 'edit': mock the editor subprocess to simulate a successful file modification
        def mock_editor(command_parts: list[str], **kwargs: object):
            temp_file_path = Path(command_parts[-1])
            temp_file_path.write_text("newly edited content")
            mock_proc = mocker.MagicMock()
            mock_proc.returncode = 0
            return mock_proc

        mocker.patch("aico.commands.edit.subprocess.run", side_effect=mock_editor)

    result = runner.invoke(app, args, catch_exceptions=False)

    assert result.exit_code == 0, (
        f"Command '{command_str}' failed unexpectedly.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_load_from_shared_history_restores_all_fields(tmp_path: Path) -> None:
    """Tests that SharedHistoryPersistence.load correctly restores all fields, including user/assistant metadata."""
    # GIVEN a shared history setup with rich metadata in history records
    project_dir = tmp_path / "project"
    history_root = project_dir / ".aico" / "history"
    sessions_dir = project_dir / ".aico" / "sessions"
    store = HistoryStore(history_root)

    user_derived = UserMetaEnvelope(aico_user_meta=UserDerivedMeta(passthrough=True, piped_content="piped"))
    asst_derived = DerivedContent(unified_diff="diff", display_content="display")
    asst_tokens = TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)

    u_idx = store.append(
        HistoryRecord(role="user", content="u", mode=Mode.CONVERSATION, timestamp="ts_u", derived=user_derived)
    )
    a_idx = store.append(
        HistoryRecord(
            role="assistant",
            content="a",
            mode=Mode.DIFF,
            timestamp="ts_a",
            model="m_rec",
            token_usage=asst_tokens,
            cost=0.5,
            duration_ms=500,
            derived=asst_derived,
        )
    )

    view = SessionView(model="m_view", context_files=[], message_indices=[u_idx, a_idx])
    view_path = sessions_dir / "main.json"
    save_view(view_path, view)
    pointer_file = project_dir / ".ai_session.json"
    switch_active_pointer(pointer_file, view_path)

    # WHEN SharedHistoryPersistence.load is called
    from aico.core.session_persistence import SharedHistoryPersistence
    from aico.lib.models import AssistantChatMessage, UserChatMessage

    persistence = SharedHistoryPersistence(pointer_file)
    _, session_data = persistence.load()

    # THEN the loaded SessionData contains all the restored fields
    assert len(session_data.chat_history) == 2
    user_msg, asst_msg = session_data.chat_history

    assert isinstance(user_msg, UserChatMessage)
    assert user_msg.timestamp == "ts_u"
    assert user_msg.passthrough is True
    assert user_msg.piped_content == "piped"

    assert isinstance(asst_msg, AssistantChatMessage)
    assert asst_msg.timestamp == "ts_a"
    assert asst_msg.model == "m_rec"
    assert asst_msg.cost == 0.5
    assert asst_msg.duration_ms == 500
    assert asst_msg.token_usage is not None
    assert asst_msg.token_usage.prompt_tokens == 1
    assert asst_msg.derived is not None
    assert asst_msg.derived.unified_diff == "diff"
