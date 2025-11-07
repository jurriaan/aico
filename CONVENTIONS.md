# Coding Conventions for AI Assistant

**You MUST read and strictly adhere to ALL conventions in this document for EVERY code generation or modification task performed for this project.**
Do NOT add comments within the code that merely describe the diff, such as `# Added this line` or `# Changed X to Y`. Explain changes in your natural language response, not in the code diffs.
## Interaction Model: Clarify, Don't Assume

Adhere strictly to the user's request. Your primary mode of interaction should be conversational and clarifying.

-   **Clarify Ambiguity:** If a request is ambiguous, incomplete, or could be interpreted in multiple ways, you MUST ask focused, numbered questions to resolve the ambiguity before generating any code.
-   **Request Missing Context:** If you determine that the provided context is insufficient to complete a task accurately, you MUST request the missing files. Your request for files must include:
    1.  A concise justification for why the files are needed.
    2.  A single, copyable command for the user to execute, such as `aico add path/to/file_a.py`.

## Core Philosophy: A Composable Unix Tool

The fundamental design of `aico` is that of a predictable, composable Unix tool. It is a **tool, not an agent**. This principle gives rise to our most important conventions:

- **Predictable and Composable I/O:** The application MUST respect its execution context.
  - When `stdout` is piped or redirected (i.e., not a TTY), its output MUST be clean, machine-readable data (e.g., a unified diff).
  - All human-centric output (progress indicators, diagnostics, warnings, cost info) MUST be directed to `stderr` to avoid corrupting the data stream.
  - When `stdout` is connected to a TTY, its output can be enhanced for human readability (e.g., with Rich Markdown).
- **Transparent State:** All session state is human-readable and lives in your repository. `aico` supports two formats:
  - A legacy, single-file `.ai_session.json` that contains the entire session.
  - A shared-history format backed by `historystore`, which uses a tiny pointer file (`.ai_session.json`) referencing a lightweight session view (`.aico/sessions/*.json`) and a sharded, append-only history log (`.aico/history/`). There is no hidden state in either format.
- **Developer in Control:** The workflow is designed for a "Plan and Execute" model, where the developer uses `aico` to augment their own process, not replace it.
- **Targeted Generation:** Generated diffs SHOULD be small and targeted, addressing a single concern. This aligns with the "Plan and Execute" workflow where each step is a discrete change.
- **Generate Only When Instructed:** You MUST NOT generate code (e.g., `SEARCH/REPLACE` blocks) during a conversational `ask` command. Code generation is reserved for the `gen` command.

## Architectural Principles

When writing code, you MUST follow these project-specific principles:

### High-Level Architecture

- **Intent-Driven Commands:** Command names must be verbs that clearly express user intent (e.g., `ask`, `generate-patch`). This is a core design principle of the `aico` CLI.
- **Orthogonal Commands and Flags:** Prefer creating new, specific commands over adding flags that fundamentally change the behavior of an existing command (e.g., `aico gen` is better than `aico prompt --mode=diff`). Similarly, flags should be orthogonal, controlling a single, well-defined aspect of a command's behavior (e.g., `--recompute` has a single, clear purpose).
- **Principle of Centralized Logic:** Core logic shared between multiple commands (like invoking the LLM, managing session state, or processing output) should be centralized in helper functions or dedicated modules. This avoids code duplication and ensures a consistent user experience across different commands (e.g., `gen` and `last` should display diffs consistently).
- **Principle of Streaming Abstractions:** For operations that involve parsing complex, multi-part data streams (especially from LLMs), prefer creating a generator-based streaming parser. This pattern isolates the complex parsing logic and provides a clean, iterable interface for consumers, simplifying the command-level code.
- **Atomic Operations:** Critical file operations, especially session writing, must be atomic to prevent data corruption. Use a temporary file + rename pattern.
- **Simplicity and Readability:** Keep the code as simple as possible. Use self-explanatory identifier names over comments. Do not add docstrings to simple methods/functions.

### Modern Python and Type Safety

- **Comprehensive Type Hinting:** This is MANDATORY for all function signatures (parameters and return types) and significant variable declarations.
- **Static Type Checking:** All code MUST pass `basedpyright` type-checking without any errors or warnings.
- **Pydantic for Data Contracts:** Use Pydantic models for all data structures that are serialized/deserialized (e.g., `.ai_session.json`) or received from external APIs. This is our primary mechanism for ensuring data integrity and preventing runtime errors from corrupt files or unexpected API changes.
- **Contracts for Untyped Libraries:** Use `typing.Protocol` with `@runtime_checkable` to create a defensive boundary around external library objects that lack precise types (e.g., `litellm` response objects). This insulates our code from upstream changes and makes our internal logic more predictable.
- **Immutability for Data Models:** When defining Pydantic models or dataclasses that represent data that should not be mutated after creation (such as historical log entries like `ChatMessageHistoryItem`), prefer making them immutable (e.g., using `frozen=True`). This prevents bugs related to accidental state modification.
- **Specific Collection Types:** Use specific collection types from `collections.abc` (like `Mapping`, `Sequence`) in type hints over generic `dict` or `list` where appropriate.
- **Enums for Finite Sets:** Use `enum.Enum` for fixed sets of values (like `Mode`) to ensure type safety and prevent magic strings.
- **Latest Python Features:** Write code using the latest stable Python version and its modern features, such as:
  - PEP 604 Union Types: `int | None`
  - PEP 636 Pattern Matching: `match/case`
  - PEP 695 New Generics Syntax: `type MyList[T] = list[T]`

## Testing

- **GIVEN/WHEN/THEN Structure:** Use `GIVEN`, `WHEN`, `THEN` (or `AND`) comments for the different parts of a test to ensure clarity.
- **Isolated Filesystems:** CLI tests that interact with the filesystem MUST use `typer.testing.CliRunner.isolated_filesystem` to ensure tests are hermetic and do not interfere with each other.
- **Mock External Services:** All external API calls, particularly to LLMs, MUST be mocked using `pytest-mock`.
- **Prefer Helper Functions:** For repetitive test setup (like initializing sessions and mocking API calls), prefer creating a dedicated helper function over complex `pytest.mark.parametrize` fixtures to keep individual tests readable and self-contained.

## Addon Development Conventions

To ensure addons integrate seamlessly and provide a consistent user experience, they SHOULD adhere to the following conventions:

- **Discovery:** Addons must be executable and placed in one of the standard addon directories (`./.aico/addons/` or `~/.config/aico/addons/`).
- **Help Text:** An addon must provide a single line of help text by responding to a `--usage` flag.
- **Session Interaction:** An addon MUST use the `AICO_SESSION_FILE` environment variable to locate and interact with the session state, ensuring portability.
- **Delegation:** Complex addons are encouraged to delegate to `aico`'s built-in commands (e.g., `aico prompt --passthrough`) for core functionality rather than re-implementing it.
