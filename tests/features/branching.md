# Feature: Session Branching

`aico` supports Git-like branching for conversations. This allows you to fork a session to experiment with a solution. If it fails, you can switch back to the main branch and try a different approach, keeping your history clean.

## 1. Setup and Base Context

Initialize the session and establish the shared context.

```console
$ aico init --model "openai/test-model" #=> --regex Initialized session file: .*\.ai_session\.json
$ aico ask "Explain this code"
This code is a Python script.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.02
$
```

## 2. Forking for Experimentation (Solution A)

We decide to try "Solution A". We fork the session so we don't pollute the `main` history.

```console
$ aico session-fork solution-a
Forked new session 'solution-a' and switched to it.
$ aico ask "Propose Solution A"
Implementing Solution A using a loop.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.04
$
```

Verify we are on the new branch and the history is active.

```console
$ aico session-list
Available sessions:
  - main
  - solution-a (active)
$ aico last
Implementing Solution A using a loop.
$
```

## 3. Switching Back

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

## 5. Verification of Isolation

We now have three sessions. `main` is clean, `solution-a` has the loop approach, and `solution-b` has the recursive approach.

```console
$ aico session-switch solution-a
Switched active session to: solution-a
$ aico last
Implementing Solution A using a loop.
$ aico session-switch solution-b
Switched active session to: solution-b
$ aico last
Implementing Solution B using recursion.
$
```
