# pyright: standard
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.lib.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
from aico.lib.session import SESSION_FILE_NAME, save_session

runner = CliRunner()


@pytest.fixture
def session_with_two_pairs(tmp_path: Path) -> Iterator[Path]:
    """Creates a session with 2 user/assistant pairs within an isolated filesystem."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = []
        for i in range(2):
            history.append(
                UserChatMessage(
                    role="user",
                    content=f"user prompt {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"ts{i}",
                    is_excluded=False,
                )
            )
            history.append(
                AssistantChatMessage(
                    role="assistant",
                    content=f"assistant response {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"ts{i}",
                    model="test-model",
                    duration_ms=100,
                    is_excluded=False,
                )
            )
        session_data = SessionData(model="test", context_files=[], chat_history=history)
        session_file = Path(td) / SESSION_FILE_NAME
        save_session(session_file, session_data)
        yield session_file
