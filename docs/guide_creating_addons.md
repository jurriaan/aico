# Guide: Creating custom addons

`aico` is designed to be extended via scripts. You don't need to learn a complex plugin API; if you can write an executable script (Shell, Python, Ruby, etc.), you can extend the tool.

## How it works

Any executable file in a recognized addon directory becomes a subcommand. `aico` looks for scripts in this order (first one found wins):

1.  **Project-level:** `./.aico/addons/`
2.  **User-level:** `~/.config/aico/addons/`
3.  **Bundled:** Built-in default scripts.

The tool communicates with your script via environment variables:
- `AICO_SESSION_FILE`: The full path to the active `.ai_session.json`.
- `PYTHONPATH`: Automatically set so you can `import aico` if writing in Python. (Note: The internal Python API is currently considered unstable).

### Design patterns for addons

For complex scripting, we recommend two main patterns:
1. **Delegation**: Most addons should delegate the heavy lifting to `aico`'s built-in commands like `ask`, `gen`, or `dump-history`.
2. **Passthrough for Fine Control**: Advanced scripts (like the bundled `commit` addon) use `aico prompt --passthrough`. This bypasses `aico`'s default prompt engineering (no system instruction or XML tags), providing a "raw pipe" to the LLM.

In this guide, we will create a simple command called `greet` that wraps a prompt.

## 1. Setup

Initialize a session.

```console
$ aico init --model "openai/test-model"
Initialized session file: .ai_session.json
$
```

## 2. Writing the addon

Addons are simply executable files placed in `.aico/addons/`.

We will create a script named `greet`. It uses the `$AICO_SESSION_FILE` environment variable injected by `aico`.

```console
$ mkdir -p .aico/addons
$ echo '#!/bin/sh' > .aico/addons/greet
$ echo 'if [ "$1" = "--usage" ]; then echo "Greets the user via the LLM."; exit 0; fi' >> .aico/addons/greet
$ echo 'echo "Running addon for session: $(basename "$AICO_SESSION_FILE")"' >> .aico/addons/greet
$ echo 'aico ask "Say hello to ${1:-User}"' >> .aico/addons/greet
$ chmod +x .aico/addons/greet
$
```

## 3. Usage

By default, `aico` ignores local project addons for security. We must explicitly trust the project directory once.

```console
$ aico trust | sed 's|project: .*|project: <path>|'
Success: Trusted project: <path>
Local addons in .aico/addons/ will now be loaded.
$
```

Now the command is available and appears in the help menu.

```console
$ aico greet World
Running addon for session: .ai_session.json
Hello, World! I am an addon.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.02
$ aico --help | grep greet | sed 's/[│]//g; s/^ *//; s/ *$//; s/  */ /g'
greet Greets the user via the LLM.
$
```
