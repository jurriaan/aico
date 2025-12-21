# aico

`aico` gives you precise, scriptable control over Large Language Models, right from your terminal. It provides a **structured interface to the LLM**, treating it as a command-line utility, not an opaque agent.

You explicitly manage the context by `add`ing and `drop`ping files, control the conversation history, and receive output as standard text or unified diffs, perfect for piping into `patch`, `delta`, or your own scripts. Built on the philosophy that the developer is always in command, `aico` is designed to be a transparent and composable part of your existing toolchain.

## Installation

Install `aico` using `uv`:

```bash
uv tool install --from git+https://github.com/jurriaan/aico/ aico
```

## Configuration

`aico` supports OpenAI models directly and non-OpenAI models (e.g., Claude, Gemini) via OpenRouter. Set the appropriate API key as an environment variable.

For example:

-   For OpenAI models (like `openai/gpt-4o`):
    ```bash
    export OPENAI_API_KEY="sk-..."
    ```
-   For non-OpenAI models via OpenRouter (like `openrouter/anthropic/claude-3.5-sonnet` or `openrouter/google/gemini-flash-1.5`):
    ```bash
    export OPENROUTER_API_KEY="sk-..."
    ```

You specify which model to use when you initialize a session. Use the `openai/` prefix for OpenAI models and `openrouter/` for others:

```bash
aico init --model "openrouter/google/gemini-3-pro-preview"
```

**Note:** All models must use the explicit provider prefix (`openai/<model>` or `openrouter/<model>`). OpenRouter provides access to models from Anthropic, Google, Meta, and many others.

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

- **Transparent State.** There is no hidden state or magic. `aico` uses a transparent storage architecture: a tiny pointer file (`.ai_session.json`) references a lightweight session view (`.aico/sessions/*.json`) and a sharded, append-only history log (`.aico/history/`). This enables git-like branching via views while keeping all data inspectable and versionable.

- **Focused on Code Modification.** The `aico gen` (`generate-patch`) command is optimized to produce standard unified diffs, making it ideal for refactoring, adding features, or fixing bugs directly from your terminal.

## Features

- **Streaming Output:** See the AI's response in real-time. With the `gen` command, watch as diffs are generated and rendered in-place.
- **Branching Workflows:** Fork conversations to try different solutions without duplicating history data. Switch between session branches seamlessly to manage different tasks or experiments.
- **Context Management:** Explicitly `add` and `drop` files to control exactly what the AI sees.
- **History Control:** Easily manage how much of the conversation history is included in the next prompt to balance context-awareness with cost.
- **Cost and Token Tracking:** See token usage and estimated cost for each interaction.
- **Standard Tooling:** Includes built-in commands for `commit` generation, session `summarize`ation, and interactive context management.
- **Editor-Agnostic:** Because it's a CLI tool, `aico` works with any code editor, from Vim to VSCode.

## Branching and Sessions

Because `aico` uses a pointer-based architecture, it supports branching workflows by default. All commands, including mutating ones (e.g., `ask`, `gen`, `edit`, `undo/redo`, `set-history`, and context/model updates), work seamlessly across branches. You can fork conversations to try different solutions without duplicating the entire history data.

## Basic Workflow: Plan and Execute

*Note: for a more comprehensive guide on how to use `aico` in a production setting, see [the example workflows](EXAMPLE_WORKFLOWS.md) document.*

An effective way to use `aico` is to first collaborate with the AI on a plan, and then ask it to execute each step of that plan.

These are common steps in such a workflow:

1. **Initialize a session in your project root.**

   ```bash
   aico init --model "openrouter/google/gemini-3-pro-preview"
   ```

2. **Define the context boundary.** Add relevant files to the AI's context. Keep it focused: `drop` files when they are no longer needed to prevent hallucinations and reduce token costs.

   ```bash
   aico add src/utils.py src/main.py
   ```

3. **(Optional) Check the context size and cost.** Before sending a complex prompt, you can see how large the context will be and the estimated cost.

   ```bash
   aico status
   ```

4. **Plan the work. Start a conversation with the AI to create a plan.**

   ```bash
   aico ask "Propose a multi-increment, test-driven plan to refactor the 'hello' function in main.py. It should accept a 'name' argument and print a greeting."
   ```

   The AI will respond with a numbered plan. This starts a conversation that becomes part of the session history.

5. **Execute one step. Ask the AI to write the code for the first increment.**

   ```bash
   aico gen "Implement Increment 1 of the plan."
   ```

   `aico` will stream a response, ending with a proposed diff.

6. **Review, Apply, and Correct.**

   ```bash
   # Review the diff from the last command with a tool like delta
   aico last | delta

   # If the patch is correct, apply it
   aico last | patch -p1

   # Small mistake (e.g., naming error)? Fix the history directly so the AI "learns".
   aico edit

   # Wrong approach? Undo the last interaction and re-prompt.
   aico undo
   ```

Repeat steps 5 and 6 for each increment of the plan.

**Finished the feature?**
Use the [`summarize`](#standard-addons) addon to archive your current history and reset the context for the next task:
```bash
aico summarize
```

For more detailed usage examples and tutorials, see the [docs/](docs/) directory.

## Commands Overview

- `aico init`: Creates a `.ai_session.json` pointer and initializes the session directory.
- `aico add <files...>`: Adds one or more files to the session context.
- `aico drop <files...>`: Removes one or more files from the context.
- `aico ask "<instruction>"`: Have a conversation with the AI for planning and discussion.
- `aico gen | generate-patch "<instruction>"`: Generate code modifications as a unified diff.
- `aico prompt "<instruction>"`: A power-user command for sending unformatted prompts. Primarily intended for scripting or addons. Prefer `ask` or `gen` for general use.
- `aico dump-history`: Exports the active chat history to `stdout` in a machine-readable format. Useful for scripting and addons.
- `aico last [index]`: Shows the response from the message pair at the given index (e.g., `0` for the first pair, `-1` for the last). Defaults to `-1`.
  - `--prompt`: Shows the user's prompt message instead of the AI's response.
  - `--recompute`: Re-applies the original instruction to the current file state. Useful for retrying a command after adding/changing context.
  - `--verbatim`: Prints the original, unprocessed response from the AI.
- `aico edit [index]`: Open the content of a message in your default editor (`$EDITOR`) to make manual corrections. Use `--prompt` to edit the user prompt instead of the assistant response.
- `aico undo [indices...]`: Marks message pairs as excluded. Supports single indices (`0`), lists (`0 1`), and inclusive ranges (`0..2` or `-3..-1`). Defaults to `-1`.
- `aico redo [indices...]`: Re-includes previously excluded message pairs. Supports single indices, lists, and ranges (e.g., `aico redo 0..2`).
- `aico status`: Shows a comprehensive summary of the session status, including token usage, estimated cost, and chat history configuration.
- `aico log`: Show a compact `git log`-style view of the active conversation context.
- `aico set-history <index>`: Set which message pair the active history starts from. For example, `aico set-history 0` makes the full history active.
- `aico session-list`: List available session branches.
- `aico session-switch <name>`: Switch the active branch.
- `aico session-fork <name>`: Create a new branch from the current one.
- `aico session-new <name>`: Create a new, empty session branch.

## Addons: Extending `aico`

`aico` comes with a set of standard addons enabled by default, but also allows you to create custom commands using a simple script-based system.

### Standard Addons

These commands are built-in but implemented as addons, meaning you can inspect or override them if needed.

- [`aico commit`](.aico/addons/commit): Generates a Conventional Commit message for staged changes, using both your `git diff` and the `aico` conversation log for context.
- [`aico summarize`](.aico/addons/summarize): Archives history as timestamped `.aico/summaries/YYYYMMDDTHHMMSS_PROJECT_SUMMARY.md`, symlinks `PROJECT_SUMMARY.md` at root, resets active history, adds to context.
- [`aico manage-context`](.aico/addons/manage-context): Lets you interactively manage the session context using `git ls-files` and `fzf`, preselecting files already in context so you can quickly add or drop files without remembering exact paths.

### Customizing and Overriding

`aico` looks for addons in the following order. The first one found wins, allowing you to override standard addons with your own versions.

1.  **Project-specific:** `./.aico/addons/` (Highest priority)
2.  **User-specific:** `~/.config/aico/addons/`
3.  **Bundled:** Built-in defaults (Lowest priority)

### Creating Your Own Addon

An addon is simply an executable script placed in one of the addon directories.

1.  **Create a script** (e.g., `my-command`):
    ```bash
    #!/bin/bash
    # Use AICO_SESSION_FILE to read the current session state
    echo "Current session: $AICO_SESSION_FILE"
    ```
2.  **Make it executable**: `chmod +x my-command`
3.  **Add help text**: The script must print a single line of help text when run with `--usage`.
    ```bash
    if [ "$1" == "--usage" ]; then
      echo "My custom command description"
      exit 0
    fi
    ```

For complex addons, you can write them in Python and leverage `aico`'s internal libraries (the `PYTHONPATH` is automatically propagated). But note that the internal API is not stable at the moment.

## Contributing

This is a tool I use personally; PRs are welcome but feature requests may be declined to keep the tool focused.

### Development

```bash
# Run linting and type checking
./script/lint

# Run tests
./script/test
```
