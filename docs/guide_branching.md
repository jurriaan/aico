# Guide: Session Branching

`aico` supports Git-like branching for conversations. This allows you to fork a session to experiment with a solution. If it fails, you can switch back to the main branch and try a different approach, keeping your history clean.

> **Architecture Note:** Because `aico` uses a pointer-based storage system, branching is **zero-copy**. It simply creates a new lightweight view referencing the existing history log.

## 1. Setup

Initialize the session.

```console
$ aico init --model "openai/test-model"
Initialized session file: .ai_session.json
$ aico ask "Explain this code"
This code is a Python script.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.02
$
```

## 2. Forking a Session

We want to experiment with "Solution A". We fork the session so we don't pollute the `main` history.

```console
$ aico session-fork solution-a
Forked new session 'solution-a' and switched to it.
$ aico ask "Propose Solution A"
Implementing Solution A using a loop.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.04
$
```

Verify we are on the new branch.

```console
$ aico session-list
Available sessions:
  - main
  - solution-a (active)
$
```

## 3. Switching Branches

"Solution A" didn't work out. We switch back to `main`.

```console
$ aico session-switch main
Switched active session to: main
$
```

Verify that the history in `main` does **not** contain the conversation about Solution A. It should only show the initial explanation.

```console
$ aico last
This code is a Python script.
$
```

## 4. Forking for Solution B

Now we try "Solution B" from the clean state of `main`.

```console
$ aico session-fork solution-b
Forked new session 'solution-b' and switched to it.
$ aico ask "Propose Solution B"
Implementing Solution B using recursion.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.04
$
```

