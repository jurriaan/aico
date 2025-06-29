# Coding Conventions for AI Assistant

**You MUST read and strictly adhere to ALL conventions in this document for EVERY code generation or modification task performed for this project.**
Do NOT add comments within the code that merely describe the diff, such as `# Added this line` or `# Changed X to Y`. Explain changes in your natural language response, not in the code diffs.
Adhere strictly to the user's request. If a request is ambiguous or critical information is missing, **always clarify by asking focused questions** before proceeding. Do not generate code until the necessary information is provided.

## Architecture and Design Principles

When writing code, you MUST follow these project-specific principles:

### High-Level Architecture

- **Intent-Driven Commands:** Command names must be verbs that clearly express user intent (e.g., `ask`, `edit`). This is a core design principle of the `aico` CLI.
- **Composable Output:** Primary outputs should be standard formats (like unified diffs) that integrate cleanly with other Unix tools.
- **Shared Logic:** Extract common functionality into reusable components or helper functions rather than duplicating logic across commands.
- **Atomic Operations:** Critical file operations, especially session writing, must be atomic to prevent data corruption. Use a temporary file + rename pattern.
- **Streaming Interfaces:** For long-running operations like LLM calls, use streaming to provide immediate feedback to the user.
- **Simplicity and Readability:** Keep the code as simple as possible. Use self-explanatory identifier names over comments. Do not add docstrings to simple methods/functions.

### Modern Python and Type Safety

- **Comprehensive Type Hinting:** This is MANDATORY for all function signatures (parameters and return types) and significant variable declarations.
- **Static Type Checking:** All code MUST pass `basedpyright` type-checking without any errors or warnings.
- **Pydantic for Data Contracts:** Use Pydantic models for all data structures that are serialized/deserialized (e.g., `.ai_session.json`) or received from external APIs. This is our primary mechanism for ensuring data integrity and preventing runtime errors from corrupt files or unexpected API changes.
- **Contracts for Untyped Libraries:** Use `typing.Protocol` with `@runtime_checkable` to create a defensive boundary around external library objects that lack precise types (e.g., `litellm` response objects). This insulates our code from upstream changes and makes our internal logic more predictable.
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
