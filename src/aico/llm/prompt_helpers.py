"""Utilities for reconstructing historical messages into LLM API format."""

from collections.abc import Sequence

from aico.models import (
    AssistantChatMessage,
    ChatMessageHistoryItem,
    LLMChatMessage,
    UserChatMessage,
)


def reconstruct_historical_messages(
    history: Sequence[ChatMessageHistoryItem],
) -> list[LLMChatMessage]:
    reconstructed: list[LLMChatMessage] = []

    for msg in history:
        reconstructed_msg: LLMChatMessage
        match msg:
            case UserChatMessage(passthrough=True) as m:
                reconstructed_msg = {"role": "user", "content": m.content}
            case UserChatMessage(content=str(prompt), piped_content=str(piped_content)):
                reconstructed_msg = {
                    "role": "user",
                    "content": (
                        f"<stdin_content>\n{piped_content}\n</stdin_content>\n" + f"<prompt>\n{prompt}\n</prompt>"
                    ),
                }
            case UserChatMessage(content=str(prompt)):
                reconstructed_msg = {
                    "role": "user",
                    "content": f"{prompt}",
                }
            case AssistantChatMessage(content=str(content)):
                reconstructed_msg = {"role": "assistant", "content": content}

        reconstructed.append(reconstructed_msg)
    return reconstructed
