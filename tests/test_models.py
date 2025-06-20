from typing import Any

from aico.models import AssistantChatMessage, SessionData, UserChatMessage


def test_session_data_migration_from_old_format() -> None:
    # GIVEN an old-format session data dictionary
    old_session_data: dict[str, Any] = {
        "model": "old-model-for-testing",
        "history_start_index": 1,
        "context_files": ["file.py"],
        "chat_history": [
            {
                "role": "user",
                "content": "This is a prompt from an old session.",
                "mode": "raw",
                "token_usage": None,  # This field will be removed
                "cost": None,  # This field will also be removed
            },
            {
                "role": "assistant",
                "content": "This is a response from an old session.",
                "mode": "diff",
                "token_usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                },
                "cost": 0.0001,
            },
        ],
        "last_response": None,
    }

    # WHEN the data is validated against the SessionData model
    session = SessionData.model_validate(old_session_data)

    # THEN the chat history is migrated into the new, richer models
    assert len(session.chat_history) == 2

    # AND the user message is a UserChatMessage
    user_msg = session.chat_history[0]
    assert isinstance(user_msg, UserChatMessage)
    assert user_msg.role == "user"
    assert user_msg.content == "This is a prompt from an old session."
    assert user_msg.mode == "raw"
    assert "timestamp" in user_msg.model_dump()
    # verify old fields are gone
    assert "token_usage" not in user_msg.model_dump()
    assert "cost" not in user_msg.model_dump()

    # AND the assistant message is an AssistantChatMessage
    assistant_msg = session.chat_history[1]
    assert isinstance(assistant_msg, AssistantChatMessage)
    assert assistant_msg.role == "assistant"
    assert assistant_msg.content == "This is a response from an old session."
    assert assistant_msg.mode == "diff"
    assert assistant_msg.token_usage.total_tokens == 30
    assert assistant_msg.cost == 0.0001

    # AND new fields were added with sensible defaults
    assert assistant_msg.model == "old-model-for-testing"
    assert "timestamp" in assistant_msg.model_dump()
    assert assistant_msg.duration_ms == -1
