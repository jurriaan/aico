# Feature: Session Initialization and Context Management

To get started with `aico`, you first initialize a session in your project. This creates a controlled environment where you can explicitly manage which files the AI has access to, giving you full transparency and control over the context from the very beginning.

## Scenario: A user initializes a session and manages the file context

Let's walk through a typical workflow. This example shows how to start a new session, and then add or remove files to precisely define the AI's context.

- Given I am in a new project directory without an existing session
- And a file named "CONVENTIONS.md" exists
- And a file named "test.py" exists

First, let's initialize `aico` to create the session.

- When I run the command `aico init --model "test-model"`
- Then the command should succeed
- And a file named ".ai_session.json" should be created
- And the session context should be empty

With the session active, you can now populate the context with the files you want the AI to consider.

- When I run the command `aico add CONVENTIONS.md test.py`
- Then the command should succeed
- And the session context should contain the file "CONVENTIONS.md"
- And the session context should contain the file "test.py"

Conversely, you can easily remove files to keep the context lean and focused.

- When I run the command `aico drop test.py`
- Then the command should succeed
- And the session context should contain the file "CONVENTIONS.md"
- And the session context should not contain the file "test.py"

# Feature: Token and Cost Transparency

## Scenario: A user checks the token and cost breakdown for the current context

Understanding context size is crucial for managing API costs and model performance. This scenario shows how the `status` command gives you a transparent, real-time breakdown of your token usage, so there are never any surprises.

- Given a project with an initialized aico session for model "test-model-with-cost"
- And the file "CONVENTIONS.md" is in the session context
- And the chat history contains one user/assistant pair
- And for this scenario, the token counter will report pre-defined counts
- And the model "test-model-with-cost" has a known cost per token
- When I run the command `aico status`
- Then the output should be:
  ```
  ╭────────────────────────────────────────────────── Status for model ──────────────────────────────────────────────────╮
  │                                                 test-model-with-cost                                                 │
  ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
  
          Tokens              Cost Component
  ────────────── ───────────────── ───────────────────────────────────────────────────────────────────────────────────────
             100          $0.01000 system prompt
              50          $0.00500 alignment prompts (worst-case)
              75          $0.00750 chat history
                                     └─ Active window: 1 pair (ID 0), 1 sent.
                                        (Use `aico log`, `undo`, and `set-history` to manage)
  ────────────── ───────────────── ────────────────────────────────── Context Files (1) ──────────────────────────────────
             200           $0.0200 CONVENTIONS.md
  ────────────── ───────────────── ───────────────────────────────────────────────────────────────────────────────────────
             425           $0.0425 Total
  
  ╭─────────────────────────────────────────────────── Context Window ───────────────────────────────────────────────────╮
  │                                         (425 of 8,192 used - 95% remaining)                                          │
  │ ━━━━━━                                                                                                               │
  ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
  ```

# Feature: Core Generative Interaction

When the context is set up the way you like it, you can get to work.

## Scenario: A user asks a conversational question via an `ask` command

The `ask` command is ideal for high-level planning and conversational questions. Here, we'll ask the AI to create a simple plan before we proceed with generating any code.

- Given a project with an initialized aico session for model "test-model"
- And for this scenario, the LLM will stream the response:
  ```
  This is the plan. Step 1...
  ```
- When I run the command `aico ask "Create a plan for the feature we just discussed"`
- Then the output should be:
  ```
  This is the plan. Step 1...
  ```
- And the session history should contain 1 user/assistant pair

## Scenario: A user modifies an existing file via a `gen` command

With a plan in mind, you can use the `gen` command to execute the steps. This example shows how `aico` can modify an existing file that's already in the session context.

- Given a project with an initialized aico session for model "test-model"
- And the file "file_to_modify.py" is in the session context:
  ```python
  def hello():
      print("Hello, world!")
  ```
- And for this scenario, the LLM will stream the response:
  ```
  File: file_to_modify.py
  <<<<<<< SEARCH
  def hello():
      print("Hello, world!")
  =======
  def greeting():
      print("Hello, greeting!")
  >>>>>>> REPLACE
  ```
- When I run the command `aico gen "Execute step 1 of the plan"`
- Then the output should be:
  ```diff
  --- a/file_to_modify.py
  +++ b/file_to_modify.py
  @@ -1,2 +1,2 @@
  -def hello():
  -    print("Hello, world!")
  +def greeting():
  +    print("Hello, greeting!")
  ```
- And the session history should contain 1 user/assistant pair

## Scenario: A user creates a new file via a `gen` command

The `gen` command can also create entirely new files.

- Given a project with an initialized aico session for model "test-model"
- And for this scenario, the LLM will stream the response:
  ```
  File: new_file.py
  <<<<<<< SEARCH
  =======
  def main():
      pass
  >>>>>>> REPLACE
  ```
- When I run the command `aico gen "Execute step 2 of the plan"`
- Then the output should be:
  ```diff
  --- /dev/null
  +++ b/new_file.py
  @@ -0,0 +1,2 @@
  +def main():
  +    pass
  ```
- And the session history should contain 1 user/assistant pair

# Feature: Reviewing and Applying Changes

`aico` is designed for a safe, review-first workflow. Rather than modifying your files directly, it streams a standard diff to the terminal.

## Scenario: A user reviews and applies an AI-generated change

First, we'll generate a change with `aico gen`. Then, we'll use `aico last` to retrieve that change and pipe it to the `patch` utility to apply it to our local file.

- Given a project with an initialized aico session for model "test-model"
- And the file "file_to_modify.py" is in the session context:
  ```python
  def hello():
      print("Hello, world!")
  ```
- And for this scenario, the LLM will stream the response:
  ```
  File: file_to_modify.py
  <<<<<<< SEARCH
  def hello():
      print("Hello, world!")
  =======
  def greeting():
      print("Hello, greeting!")
  >>>>>>> REPLACE
  ```
- When I run the command `aico gen "Execute step 2 of the plan"`
- Then the session history should contain 1 user/assistant pair
- When I run the command `aico last | patch -p1`
- Then the command should succeed
- And the file "file_to_modify.py" should contain:
  ```python
  def greeting():
      print("Hello, greeting!")
  ```

# Feature: History Management

To maintain a clean and relevant context, `aico` lets you manage the conversation history. You can exclude specific interactions from being included in future prompts, which helps refine the AI's focus and manage token usage.

## Scenario: A user excludes a specific conversational turn from future prompts

If the AI's last response wasn't helpful, `aico undo` removes that interaction from the session history. This example shows how to exclude the most recent conversational pair so it won’t influence the next turn.

- Given a project with an initialized aico session for model "test-model"
- And the file "file_to_modify.py" is in the session context
- And for this scenario, the LLM will stream the response:
  ```
  File: file_to_modify.py
  <<<<<<< SEARCH
  def hello():
      print("Hello, world!")
  =======
  def greeting():
      print("Hello, greeting!")
  >>>>>>> REPLACE
  ```
- When I run the command `aico gen "Replace world with greeting in the file file_to_modify.py"`
- Then the command should succeed
- When I run the command `aico undo`
- Then the output should be:
  ```
  Marked pair at index 0 as excluded.
  ```

## Scenario: A user corrects a conversational turn using undo and redo

The `undo` and `redo` commands provide a simple way to manage the active conversation history. If a generative step goes in the wrong direction, you can `undo` it. If you change your mind, you can `redo` it to bring it back into context.

- Given a project with an initialized aico session for model "test-model"
- And the chat history contains one user/assistant pair
- When I run the command `aico undo`
- Then the output should be:
  ```
  Marked pair at index 0 as excluded.
  ```
- And the session history should contain 1 user/assistant pair
- When I run the command `aico redo`
- Then the output should be:
  ```
  Re-included pair at index 0 in context.
  ```

## Scenario: A user exports the active history for scripting

The `dump-history` command provides a machine-readable export of the active conversation log, which is ideal for scripting and creating complex addon workflows.

- Given a project with an initialized aico session for model "test-model"
- And the chat history contains one user/assistant pair with content "User prompt" and "Assistant response"
- When I run the command `aico dump-history`
- Then the output should be:
  ```
  <!-- llm-role: user -->
  User prompt

  <!-- llm-role: assistant -->
  Assistant response
  ```

## Scenario: A user edits a previous assistant response using `aico edit`

Sometimes you need to manually fix or refine an AI's response in the session history. The `edit` command opens a message in your default editor ($EDITOR), allowing you to make changes. On save, the session file is updated.

(This feature is tested non-interactively by setting the EDITOR to a helper script).

- Given a project with an initialized aico session for model "test-model"
- And the chat history contains one user/assistant pair where the assistant response is "This is the orginal response."
- And a test helper script named "fake_editor.sh" exists
- When I run the command:
  """
  EDITOR=./fake_editor.sh NEW_CONTENT="This is the corrected response." aico edit
  """
- Then the command should succeed
- And the output should be:
  ```
  Updated response for message pair 0.
  ```
- And the content of the assistant response at pair index 0 should now be "This is the corrected response."
