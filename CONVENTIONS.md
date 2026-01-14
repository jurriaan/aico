# Coding Conventions for LLM

**Read and adhere to all conventions in this document for every code generation or modification task performed for this project.**
Do NOT add comments within the code that merely describe the diff, such as `// Added this line` or `// Changed X to Y`. Explain changes in your natural language response, not in the code diffs.

## Interaction Model: Clarify, Don't Assume

Adhere to the user's request. Maintain a conversational and clarifying interaction loop.

-   **Clarify Ambiguity:** If a request is ambiguous, incomplete, or open to multiple interpretations, ask focused, numbered questions to resolve the ambiguity before generating code.
-   **Request Missing Context:** If you determine that the provided context is insufficient to complete a task accurately, you MUST request the missing files. Your request for files must include:

    1.  A concise justification for why the files are needed.
    2.  A single, copyable command for the user to execute, such as `aico add path/to/file.rs`.

## Core Philosophy: A Composable Unix Tool

The fundamental design of `aico` is that of a predictable, composable Unix tool. It is a **tool, not an agent**. This principle gives rise to our most important conventions:

- **Predictable and Composable I/O:** The application MUST respect its execution context.
  - When `stdout` is piped or redirected (i.e., not a TTY), its output MUST be clean, machine-readable data (e.g., a unified diff).
  - All human-centric output (progress indicators, diagnostics, warnings, cost info) MUST be directed to `stderr` to avoid corrupting the data stream.
  - When `stdout` is connected to a TTY, its output can be enhanced for human readability (e.g., with syntax highlighting).
- **Transparent State:** All session state is human-readable and lives in the user's repository. `aico` uses a shared-history format backed by `historystore`, which uses a tiny pointer file (`.ai_session.json`) referencing a lightweight session view (`.aico/sessions/*.json`) and a sharded, append-only history log (`.aico/history/`). There is no hidden state in this format.
- **Developer in Control:** The workflow is designed for a "Plan and Execute" model, where the developer uses `aico` to augment their own process, not replace it.
- **Targeted Generation:** Generated diffs SHOULD be small and targeted, addressing a single concern. This aligns with the "Plan and Execute" workflow where each step is a discrete change.
- **Generate Only When Instructed:** Do not generate code (e.g., `SEARCH/REPLACE` blocks) during a conversational `ask` command. Code generation is reserved for the `gen` command.

## Architectural Principles

When writing code, you MUST follow these project-specific principles:

### High-Level Architecture

- **Intent-Driven Commands:** Command names must be verbs that clearly express user intent (e.g., `ask`, `gen`). This is a core design principle of the `aico` CLI.
- **Orthogonal Commands and Flags:** Prefer creating new, specific commands over adding flags that fundamentally change the behavior of an existing command. Similarly, flags should be orthogonal, controlling a single, well-defined aspect of a command's behavior (e.g., `--recompute` in `last` has a single, clear purpose).
- **Principle of Centralized Logic:** Core logic shared between multiple commands (like invoking the LLM, managing session state, or processing output) should be centralized in helper modules (e.g., `src/llm/executor.rs`). This avoids code duplication and ensures a consistent user experience.
- **Principle of Streaming Abstractions:** For operations that involve parsing complex, multi-part data streams (especially from LLMs), prefer creating a stateful struct parser (e.g., `StreamParser`). This pattern isolates complex parsing logic and provides a clean interface for consumers.
- **Atomic Operations:** Critical file operations, especially session writing, are atomic. Use the `atomic_write_text` helper (write to temp file + rename) to prevent data corruption.
- **Simplicity and Readability:** Keep the code simple. Use self-explanatory identifier names over comments. Do not add doc comments to obvious methods/functions.

### Modern Rust and Type Safety

- **Strict Error Handling:** Use the `thiserror` crate for the `AicoError` enum. Zero-tolerance for `unwrap()` or `expect()` in logic reachable by user input, file data, or network responses. Panics are unacceptable for a CLI tool; all potential failures must be handled gracefully.
- **Unicode Safety:** Never slice strings using raw byte indices unless the offsets are derived from character-aware methods (e.g., `find` or `char_indices`). Avoid splitting multi-byte characters.
- **Deterministic Output:** When iterating over `HashMap` or `HashSet` keys for output generation (e.g., XML blocks, CLI tables, or diffs), always sort the keys first to ensure stable results.
- **Clippy & Formatting:** All code MUST be formatted with `rustfmt` and pass `clippy` lints without warnings.
- **Serde for Data Contracts:** Use `serde` (`Serialize`, `Deserialize`) for all data structures that are serialized/deserialized (e.g., `.ai_session.json`) or received from external APIs. This ensures strict schema validation.
- **Type-Driven Design:** Use Rust's type system to make invalid states unrepresentable. Prefer Enums (e.g., `Mode`, `Role`) over stringly-typed logic.
- **Immutable by Default:** Leverage Rust's default immutability. Only use `mut` when state modification is explicitly required and localized.
- **Async/Await:** Use `tokio` for asynchronous operations, particularly I/O and network calls. Ensure async functions are properly awaited and errors are handled.
- **Path Handling:** Use `std::path::Path` and `PathBuf` for all file system operations. Do not use strings for paths unless strictly necessary for display or serialization.

## Testing

- **Unit Tests:** Place unit tests in a `mod tests` block within the source file they test, or in a separate file if the module is large.
- **Isolated Filesystems:** Tests that interact with the filesystem MUST use `tempfile` to create isolated environments that clean up after themselves. Do not write to the actual `.aico` directory during tests.
- **Mock External Services:** Do not make real network calls in tests. Mock LLM responses or abstract the `LlmClient` trait where possible.
- **GIVEN/WHEN/THEN:** Use `GIVEN`, `WHEN`, `THEN` comments in complex test cases to clarify setup, action, and assertion.

## Addon Development Conventions

To ensure addons integrate seamlessly and provide a consistent user experience, they SHOULD adhere to the following conventions:

- **Discovery:** Addons must be executable scripts and placed in one of the standard addon directories (`./.aico/addons/` or `~/.config/aico/addons/`).
- **Help Text:** An addon must provide a single line of help text by responding to a `--usage` flag.
- **Session Interaction:** An addon MUST use the `AICO_SESSION_FILE` environment variable to locate and interact with the session state. It should not hardcode the session file path.
- **Delegation:** Complex addons are encouraged to delegate to `aico`'s built-in commands (e.g., `aico prompt --passthrough`) for core functionality rather than re-implementing LLM interaction logic.
- **Language Agnostic:** Addons can be written in any language (Bash, Python, Rust, etc.) as long as they are executable.
