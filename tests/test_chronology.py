# pyright: standard

import time
from datetime import UTC, datetime

from aico.llm.executor import _build_messages
from aico.models import AssistantChatMessage, ContextFile, Mode, UserChatMessage


def test_interleaved_chronology() -> None:
    """
    Verifies that files are split correctly between Static and Floating contexts
    based on their mtime relative to the chat history.
    """
    # Horizon = T=10.
    # File A (T=5) -> Static
    # File B (T=25) -> Floating.
    # Msg 1 (T=10). Msg 2 (T=20). Msg 3 (T=30).
    history = [
        UserChatMessage(content="Msg 1", mode=Mode.CONVERSATION, timestamp="2023-01-01T10:00:10Z"),
        AssistantChatMessage(
            content="Msg 2",
            mode=Mode.CONVERSATION,
            timestamp="2023-01-01T10:00:20Z",
            model="test",
            duration_ms=0,
        ),
        UserChatMessage(content="Msg 3", mode=Mode.CONVERSATION, timestamp="2023-01-01T10:00:30Z"),
    ]

    # File A: Modified before history starts (T=5)
    ts_a = datetime(2023, 1, 1, 10, 0, 5, tzinfo=UTC).timestamp()
    file_a = ContextFile("file_a.py", "content_a", ts_a)

    # File B: Modified between Msg 2 and Msg 3 (T=25)
    ts_b = datetime(2023, 1, 1, 10, 0, 25, tzinfo=UTC).timestamp()
    file_b = ContextFile("file_b.py", "content_b", ts_b)

    metadata = {"file_a.py": file_a, "file_b.py": file_b}

    messages = _build_messages(
        active_history=history,
        system_prompt="System",
        prompt_text="Prompt",
        piped_content=None,
        mode=Mode.CONVERSATION,
        file_metadata=metadata,
        passthrough=False,
        no_history=False,
    )

    # 1. System
    assert messages[0]["role"] == "system"

    # 2. Static Context (File A only)
    assert "Ground Truth" in messages[1]["content"]
    assert "file_a.py" in messages[1]["content"]
    assert "file_b.py" not in messages[1]["content"]

    # 3. History Segment 1 (Msg 1, Msg 2)
    assert messages[3]["content"] == "Msg 1"
    assert messages[4]["content"] == "Msg 2"

    # 4. Floating Context (File B)
    assert "UPDATED CONTEXT" in messages[5]["content"]
    assert "file_b.py" in messages[5]["content"]
    assert "file_a.py" not in messages[5]["content"]

    # 5. History Segment 2 (Msg 3)
    assert messages[7]["content"] == "Msg 3"

    # 6. Final Prompt
    assert messages[-1]["content"] == "Prompt"


def test_fresh_session_behavior() -> None:
    """
    Verifies that if history is empty, all files are treated as Static (Ground Truth).
    """
    ts_now = time.time()
    file_a = ContextFile("file_a.py", "content_a", ts_now)
    metadata = {"file_a.py": file_a}

    messages = _build_messages(
        active_history=[],
        system_prompt="System",
        prompt_text="Prompt",
        piped_content=None,
        mode=Mode.CONVERSATION,
        file_metadata=metadata,
        passthrough=False,
        no_history=False,
    )

    # Should have System -> Static (2) -> Alignment (2) -> Prompt (1)
    assert len(messages) == 6
    assert "Ground Truth" in messages[1]["content"]
    assert "UPDATED CONTEXT" not in messages[1]["content"]
