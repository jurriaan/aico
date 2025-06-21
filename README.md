# aico

A command-line tool for scripting AI-driven code edits.

`aico` is built to integrate Large Language Models into a traditional, terminal-based development workflow. It reads local files, takes a prompt, and produces a standard diff. It is designed to be a predictable and composable part of your existing toolchain.

## Philosophy

`aico` is guided by a few core principles that differentiate it from chat-based assistants.

*   **It's a Tool, Not an Agent.** It is a command-line utility that transforms text. It takes files and instructions as input and produces diffs or raw text as output. Its behavior is designed to be as predictable as `grep` or `sed`.

*   **Built for Composition.** One of the primary outputs of `aico` is a clean, standard unified diff printed to `stdout`. This allows it to be piped directly into other powerful command-line tools you already use.

    ```bash
    # Generate a diff and pipe it directly to git to apply it
    aico prompt --mode diff "Implement Increment 1 of the plan" | git apply

    # Or review the last generated diff with a modern diffing tool like delta
    aico last | delta
    ```

*   **Transparent State.** There is no hidden state or magic. The entire session—context files, chat history, and model configuration—is stored in a single, human-readable `.ai_session.json` file in your project's root. You can inspect it, edit it, or even version-control it.

*   **Focused on Code Modification.** The tool is optimized for its `diff` mode, which produces structured `SEARCH/REPLACE` patches. This makes it ideal for refactoring, adding features, or fixing bugs directly from your terminal.

## Features

*   **Streaming Output:** See the AI's response in real-time. In `diff` mode, watch as diffs are generated and rendered in-place.
*   **Context Management:** Explicitly `add` and `drop` files to control exactly what the AI sees.
*   **History Control:** Easily manage how much of the conversation history is included in the next prompt to balance context-awareness with cost.
*   **Cost and Token Tracking:** See token usage and estimated cost for each interaction.
*   **Editor-Agnostic:** Because it's a CLI tool, `aico` works with any code editor, from Vim to VSCode.

## Recommended Workflow: Plan and Execute

The most effective way to use `aico` is to first collaborate with the AI on a plan, and then ask it to execute each step of that plan.

1.  **Initialize a session in your project root.**
    ```bash
    aico init --model "openrouter/google/gemini-2.5-pro"
    ```

2.  **Add files to the AI's context.**
    ```bash
    aico add src/utils.py src/main.py
    ```

3.  **(Optional) Check the context size and cost.** Before sending a complex prompt, you can see how large the context will be and the estimated cost.
    ```bash
    aico tokens
    ```

4.  **Plan the work. Start a conversation with the AI to create a plan.**
    ```bash
    aico prompt "Propose a multi-increment, test-driven plan to refactor the 'hello' function in main.py. It should accept a 'name' argument and print a greeting."
    ```
    The AI will respond with a numbered plan. This starts a conversation that becomes part of the session history.

5.  **Execute one step. Ask the AI to write the code for the first increment.**
    ```bash
    aico prompt --mode diff "Implement Increment 1 of the plan."
    ```
    `aico` will stream a response, ending with a proposed diff.

6.  **Review and apply.**
    ```bash
    # Review the diff from the last command with a tool like delta
    aico last | delta
    
    # If the patch is correct, apply it
    aico last | git apply
    ```

Repeat steps 5 and 6 for each increment of the plan.

## Commands Overview

*   `aico init`: Creates a `.ai_session.json` file in the current directory.
*   `aico add <files...>`: Adds one or more files to the session context.
*   `aico drop <files...>`: Removes one or more files from the context.
*   `aico tokens`: Shows a breakdown of token usage and estimated cost for the current context.
*   `aico prompt "<instruction>"`: Sends the context and prompt to the AI. By default, this starts a conversation for planning and discussion.
    *   `--mode diff`: The AI responds with code edits; output is a unified diff.
*   `aico last`: Shows the last response from the AI. If the response contained code edits, it displays a formatted diff.
    *   `--verbatim`: Prints the original, unprocessed response from the AI.
*   `aico history`: A subcommand group for managing the chat history.
    *   `aico history view`: See the current status of the history.
    *   `aico history set <index>`: Set which message the active history starts from.
    *   `aico history reset`: Reset the history to include all messages.
