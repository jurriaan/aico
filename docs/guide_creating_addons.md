# Guide: Creating Custom Addons

`aico` is designed to be extended. You don't need to learn a complex plugin API; if you can write a shell script (or Python, or Ruby), you can write an addon.

In this guide, we will create a simple command called `greet` that wraps an AI prompt.

## 1. Setup

Initialize a session.

```console
$ aico init --model "openai/test-model"
Initialized session file: .ai_session.json
$
```

## 2. Writing the Script

Addons are simply executable files placed in `.aico/addons/`.

We will create a script named `greet`. It uses the `$AICO_SESSION_FILE` environment variable injected by `aico`.

```console
$ mkdir -p .aico/addons
$ echo '#!/bin/sh' > .aico/addons/greet
$ echo 'if [ "$1" = "--usage" ]; then echo "Greets the user via the AI."; exit 0; fi' >> .aico/addons/greet
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
greet Greets the user via the AI.
$
```
