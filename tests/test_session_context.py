# pyright: standard
from aico.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
from aico.session_context import active_message_indices


def _make_msg(role: str, content: str) -> UserChatMessage | AssistantChatMessage:
    if role == "user":
        return UserChatMessage(role="user", content=content, mode=Mode.CONVERSATION, timestamp="ts")
    return AssistantChatMessage(
        role="assistant", content=content, mode=Mode.CONVERSATION, timestamp="ts", model="m", duration_ms=0
    )


def test_active_message_indices_shared_history_signal() -> None:
    # GIVEN a SessionData object
    history = [
        _make_msg("user", "u0"),
        _make_msg("assistant", "a0"),
        _make_msg("user", "u1"),
        _make_msg("assistant", "a1"),
    ]
    session_data = SessionData(
        model="m",
        chat_history=history,
        history_start_pair=1,  # This should be ignored
        excluded_pairs=[0],  # This should also be ignored
        offset=1,
    )

    # WHEN calling active_message_indices
    indices = active_message_indices(session_data)

    # THEN it should return all indices of the provided history
    assert indices == [0, 1, 2, 3]


def test__get_active_history_filters_and_slices() -> None:
    # GIVEN a SessionData object with a mix of messages
    from aico.models import AssistantChatMessage, Mode, SessionData, UserChatMessage
    from aico.session_context import _get_active_history

    def _make_msg(role: str, content: str) -> UserChatMessage | AssistantChatMessage:
        if role == "user":
            return UserChatMessage(role="user", content=content, mode=Mode.RAW, timestamp="t")
        return AssistantChatMessage(
            role="assistant", content=content, mode=Mode.RAW, timestamp="t", model="m", duration_ms=0
        )

    history = [
        _make_msg("user", "msg 0 - pair 0, inactive"),
        _make_msg("assistant", "resp 0"),
        _make_msg("user", "msg 1 - pair 1, active"),
        _make_msg("assistant", "resp 1"),
        _make_msg("user", "msg 2 - dangling, active"),
        _make_msg("user", "msg 3 - pair 2, excluded"),
        _make_msg("assistant", "resp 2"),
    ]

    # Create a session where history starts at pair 1, and pair 2 is excluded.
    session_data = SessionData(
        model="test",
        context_files=[],
        chat_history=history,
        history_start_pair=1,  # Equivalent of legacy start_index pointing at msg 1
        excluded_pairs=[2],  # Exclude the third pair (index 2)
        offset=0,
    )

    # WHEN _get_active_history is called
    active_history = _get_active_history(session_data)

    # THEN the returned list contains only the active messages (pair 1 and the dangling message)
    assert len(active_history) == 3
    assert active_history[0].content == "msg 1 - pair 1, active"
    assert active_history[1].content == "resp 1"
    assert active_history[2].content == "msg 2 - dangling, active"
