# aico

A command-line tool for scripting AI-driven code edits.

`aico` is built to integrate Large Language Models into a traditional, terminal-based development workflow. It reads local files, takes a prompt, and produces a standard diff. It is designed to be a predictable and composable part of your existing toolchain.

## Installation

Install `aico` using `uv`:

```bash
uv tool install --from git+https://github.com/jurriaan/aico/ aico
```

## Configuration

`aico` uses [LiteLLM](https://litellm.ai/) to support a large number of models and providers. To use a specific model provider, you need to set the corresponding API key as an environment variable.

For example:

-   For OpenAI models (like `gpt-4o`):
    ```bash
    export OPENAI_API_KEY="sk-..."
    ```
-   For Anthropic models (like `claude-4-sonnet`):
    ```bash
    export ANTHROPIC_API_KEY="sk-..."
    ```
-   For OpenRouter models (like `openrouter/google/gemini-flash-1.5`):
    ```bash
    export OPENROUTER_API_KEY="sk-..."
    ```

You specify which model to use when you initialize a session:

```bash
aico init --model "openrouter/google/gemini-2.5-pro"
```

For a complete list of supported providers and the environment variables they require, please refer to the [LiteLLM Provider documentation](https://docs.litellm.ai/docs/providers).

## Philosophy

`aico` is guided by a few core principles that differentiate it from chat-based assistants.

- **It's a Tool, Not an Agent.** It is a command-line utility that transforms text. It takes files and instructions as input and produces diffs or raw text as output. Its behavior is designed to be as predictable as `grep` or `sed`.

- **Built for Composition.** One of the primary outputs of `aico` is a clean, standard unified diff printed to `stdout`. This allows it to be piped directly into other powerful command-line tools you already use.

  ```bash
  # Generate a diff and pipe it directly to patch to apply it
  aico gen "Implement Increment 1 of the plan" | patch -p1

  # Or review the last generated diff with a modern diffing tool like delta
  aico last | delta
  ```

- **Transparent State.** There is no hidden state or magic. The entire session—context files, chat history, and model configuration—is stored in a single, human-readable `.ai_session.json` file in your project's root. You can inspect it, edit it, or even version-control it.

- **Focused on Code Modification.** The `aico gen` (`generate-patch`) command is optimized to produce standard unified diffs, making it ideal for refactoring, adding features, or fixing bugs directly from your terminal.

## Features

- **Streaming Output:** See the AI's response in real-time. With the `gen` command, watch as diffs are generated and rendered in-place.
- **Context Management:** Explicitly `add` and `drop` files to control exactly what the AI sees.
- **History Control:** Easily manage how much of the conversation history is included in the next prompt to balance context-awareness with cost.
- **Cost and Token Tracking:** See token usage and estimated cost for each interaction.
- **Editor-Agnostic:** Because it's a CLI tool, `aico` works with any code editor, from Vim to VSCode.

## Recommended Workflow: Plan and Execute

The most effective way to use `aico` is to first collaborate with the AI on a plan, and then ask it to execute each step of that plan.

1. **Initialize a session in your project root.**

   ```bash
   aico init --model "openrouter/google/gemini-2.5-pro"
   ```

1. **Add files to the AI's context.**

   ```bash
   aico add src/utils.py src/main.py
   ```

1. **(Optional) Check the context size and cost.** Before sending a complex prompt, you can see how large the context will be and the estimated cost.

   ```bash
   aico tokens
   ```

1. **Plan the work. Start a conversation with the AI to create a plan.**

   ```bash
   aico ask "Propose a multi-increment, test-driven plan to refactor the 'hello' function in main.py. It should accept a 'name' argument and print a greeting."
   ```

   The AI will respond with a numbered plan. This starts a conversation that becomes part of the session history.

1. **Execute one step. Ask the AI to write the code for the first increment.**

   ```bash
   aico gen "Implement Increment 1 of the plan."
   ```

   `aico` will stream a response, ending with a proposed diff.

1. **Review and apply.**

   ```bash
   # Review the diff from the last command with a tool like delta
   aico last | delta

   # If the patch is correct, apply it
   aico last | patch -p1

   # Made a mistake? Undo the 3rd to last change by reversing its diff.
   aico last -3 | patch -p1 -R
   ```

Repeat steps 5 and 6 for each increment of the plan.

## Commands Overview

- `aico init`: Creates a `.ai_session.json` file in the current directory.
- `aico add <files...>`: Adds one or more files to the session context.
- `aico drop <files...>`: Removes one or more files from the context.
- `aico ask "<instruction>"`: Have a conversation with the AI for planning and discussion.
- `aico gen | generate-patch "<instruction>"`: Generate code modifications as a unified diff.
- `aico prompt "<instruction>"`: A power-user command for sending unformatted prompts. Primarily intended for scripting or addons (like `aico commit`). Prefer `ask` or `gen` for general use.
- `aico last [index]`: Shows the response from the message pair at the given index (e.g., `0` for the first pair, `-1` for the last). Defaults to `-1`.
  - `--prompt`: Shows the user's prompt message instead of the AI's response.
  - `--recompute`: Re-applies the original instruction to the current file state. Useful for retrying a command after adding/changing context.
  - `--verbatim`: Prints the original, unprocessed response from the AI.
- `aico undo [index]`: Marks the message pair at the given index as excluded from future context (defaults to `-1`). This "soft delete" is useful for undoing a conversational step if a `gen` or `ask` command produced an undesirable result.
- `aico status`: See a summary of the history status and active context.
- `aico log`: Show a compact `git log`-style view of the active conversation context.
- `aico set-history <index>`: Set which message pair the active history starts from. For example, `aico set-history 0` makes the full history active.
- `aico tokens`: Shows a breakdown of token usage and estimated cost for the current context.

## Addons: Extending `aico`

You can extend `aico` with custom commands using a simple addon system, making it easy to create custom workflows.

### Creating Your Own Addon

An addon can be any executable script (e.g., a shell script, Python file) that meets three simple requirements:

1.  It must be placed in an addon directory (`./.aico/addons/` for project-specific or `~/.config/aico/addons/` for global).
2.  It must be executable (`chmod +x my-addon`).
3.  It must respond to a `--usage` flag by printing a single line of help text.

The best way to learn how to write an addon is to inspect the examples provided in this repository.

### Example Addons

The repository includes two addons that serve as practical examples:

- [`commit`](.aico/addons/commit): Generates a Conventional Commit message for staged changes by piping your `git diff` into `aico prompt`.
- [`summarize`](.aico/addons/summarize): Uses `aico` to first generate a comprehensive project summary, and then resets the session history to that summary. This is a useful technique for managing context length and cost.
