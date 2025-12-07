# pyright: standard
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aico.consts import SESSION_FILE_NAME
from aico.lib.models import AssistantChatMessage, ChatMessageHistoryItem, Mode, SessionData, UserChatMessage
from tests.helpers import init_shared_session

runner = CliRunner()


@pytest.fixture
def session_with_two_pairs(tmp_path: Path) -> Iterator[Path]:
    """Creates a shared session with 2 user/assistant pairs."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history: list[ChatMessageHistoryItem] = []
        for i in range(2):
            history.append(
                UserChatMessage(
                    role="user",
                    content=f"user prompt {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"ts{i}",
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
                )
            )
        session_data = SessionData(model="test", chat_history=history)

        init_shared_session(Path(td), session_data)

        # Return the pointer file path
        yield Path(td) / SESSION_FILE_NAME


@pytest.fixture
def session_with_excluded_pairs(tmp_path: Path) -> Iterator[Path]:
    """Creates a session with 2 pairs, both excluded, within an isolated filesystem."""
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        history = []
        for i in range(2):
            history.append(
                UserChatMessage(
                    role="user",
                    content=f"user prompt {i}",
                    mode=Mode.CONVERSATION,
                    timestamp=f"ts{i}",
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
                )
            )
        session_data = SessionData(model="test", context_files=[], chat_history=history, excluded_pairs=[0, 1])

        init_shared_session(Path(td), session_data)

        yield Path(td) / SESSION_FILE_NAME
