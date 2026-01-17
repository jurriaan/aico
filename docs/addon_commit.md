# Guide: Automating commits

`aico` comes with a **bundled** `commit` command that generates Conventional Commit messages based on your staged changes and chat history. You can use it out-of-the-box without any configuration.

## How it works

The `commit` addon automatically aggregates this context before contacting the LLM:

1. **The staged diff**: It reads the actual code changes currently staged in git.
2. **Project history**: It reads recent git log entries to match the style and formatting of your existing project commits.
3. **Conversation context**: It includes the full active conversation history. This allows the AI to understand the *intent* and reasoning behind the changes (the "why") that you discussed during the session, not just the "what" visible in the diff.

**Automatic Cleanup**
Once the message is generated, it removes the specific commit-generation prompt and response from your session history. This ensures your conversation log remains focused purely on development and isn't cluttered with administrative requests.

## 1. Setup

First, initialize the aico session and context:

```console
$ aico init --model "openai/test-model"
Initialized session file: .ai_session.json
$
```

Prepare a git repository and stage some changes:

```console
$ git init -q
$ git config --global init.defaultBranch main
$ git config user.email "test@example.com"
$ git config user.name "Test User"
$ git commit --allow-empty -m "Initial commit" -q
$ echo "print('hello v1')" > main.py
$ git add main.py
$
```

## 2. Basic usage

To generate a commit, simply run `aico commit`.

By default, this generates a message and opens it in your default editor (configured via `$EDITOR` or git config) so you can review or modify it before saving.

*(Note: For this tutorial, we simulate the editor interaction by setting `GIT_EDITOR` to a command that automatically approves the message by adding a scope: `feat:` to `feat(main):`.)*

```console
$ GIT_EDITOR="sed -i 's/feat:/feat(main):/'" aico commit              #=> --regex add hello print to main.py
[main c24b2d8] feat(main): add hello print to main.py
 1 file changed, 1 insertion(+)
 create mode 100644 main.py
$
```

Verify the commit log to see the message was used.

```console
$ git log -1 --pretty=%s
feat(main): add hello print to main.py
$
```
