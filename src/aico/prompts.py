from aico.lib.models import (
    AlignmentMessage,
    BasicAssistantChatMessage,
    BasicUserChatMessage,
    Mode,
)

DIFF_MODE_INSTRUCTIONS = (
    "\n\n---\n"
    "IMPORTANT: You are an automated code generation tool. "
    "Your response MUST ONLY contain one or more raw SEARCH/REPLACE blocks. "
    "You SHOULD NOT add any other text, commentary, or markdown. "
    "Your entire response must strictly follow the format specified below.\n"
    "- To create a new file, use an empty SEARCH block.\n"
    "- To delete a file, provide a SEARCH block with the entire file content and an empty REPLACE block.\n"
    "- Prefer generating multiple, small, targeted SEARCH/REPLACE blocks over a single large one that "
    "contains the whole file.\n\n"
    "EXAMPLE of a multi-file change:\n"
    "File: path/to/existing/file.py\n"
    "<<<<<<< SEARCH\n"
    "    # code to be changed\n"
    "=======\n"
    "    # the new code\n"
    ">>>>>>> REPLACE\n"
    "File: path/to/new/file.py\n"
    "<<<<<<< SEARCH\n"
    "=======\n"
    "def new_function():\n"
    "    pass\n"
    ">>>>>>> REPLACE"
)

ALIGNMENT_PROMPTS: dict[Mode, list[AlignmentMessage]] = {
    Mode.CONVERSATION: [
        BasicUserChatMessage(
            "When I ask you to plan, discuss, or explain, your role is to be a conversational assistant. "
            + "In this mode, you MUST NOT generate code modification blocks like `SEARCH/REPLACE` or unified diffs.",
        ),
        BasicAssistantChatMessage(
            "Understood. For this turn, my response will be conversational and I will not generate "
            + "`SEARCH/REPLACE` or diff blocks.",
        ),
    ],
    Mode.DIFF: [
        BasicUserChatMessage(
            "When I ask you to implement changes, your role is to be an automated code generation tool. "
            + "In this mode, your response MUST ONLY contain one or more `SEARCH/REPLACE` blocks.",
        ),
        BasicAssistantChatMessage(
            "Acknowledged. For this turn, I will only output valid `SEARCH/REPLACE` blocks and no other commentary.",
        ),
    ],
}
