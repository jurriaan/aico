# pyright: standard
from aico.core.session_context import active_message_indices
from aico.lib.models import AssistantChatMessage, Mode, SessionData, UserChatMessage


def _make_msg(role: str, content: str) -> UserChatMessage | AssistantChatMessage:
    if role == "user":
        return UserChatMessage(role="user", content=content, mode=Mode.CONVERSATION, timestamp="ts")
    return AssistantChatMessage(
        role="assistant", content=content, mode=Mode.CONVERSATION, timestamp="ts", model="m", duration_ms=0
    )


def test_active_message_indices_shared_history_signal() -> None:
    # GIVEN a SessionData object where `history_start_index` is set (simulating a shared-history load)
    # This signals that the history is pre-sliced and is the active window.
    history = [
        _make_msg("user", "u0"),
        _make_msg("assistant", "a0"),
        _make_msg("user", "u1"),
        _make_msg("assistant", "a1"),
    ]
    session_data = SessionData(
        model="m",
        chat_history=history,
        is_pre_sliced=True,
        history_start_pair=1,  # This should be ignored because history_start_index is set
        excluded_pairs=[0],  # This should also be ignored
    )

    # WHEN calling active_message_indices
    indices = active_message_indices(session_data)

    # THEN it should return all indices of the provided history, without re-slicing
    assert indices == [0, 1, 2, 3]


def test_active_message_indices_legacy_slicing() -> None:
    # GIVEN a SessionData object for a legacy session (history_start_index is None)
    history = [
        _make_msg("user", "u0"),  # pair 0
        _make_msg("assistant", "a0"),
        _make_msg("user", "u1"),  # pair 1
        _make_msg("assistant", "a1"),
        _make_msg("user", "u2"),  # pair 2
        _make_msg("assistant", "a2"),
    ]
    session_data = SessionData(
        model="m",
        chat_history=history,
        is_pre_sliced=False,
        history_start_index=None,  # Legacy session
        history_start_pair=1,  # Active history starts at pair 1
        excluded_pairs=[2],  # Exclude pair 2
    )

    # WHEN calling active_message_indices
    indices = active_message_indices(session_data)

    # THEN it should correctly apply `history_start_pair` and `excluded_pairs`
    # Active pairs are [1]. Pair 2 is excluded.
    # Expected message indices are for pair 1: [2, 3]
    assert indices == [2, 3]
