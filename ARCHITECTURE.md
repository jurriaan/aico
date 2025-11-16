# `aico` Architecture

This document provides a high-level overview of the `aico` codebase architecture. It is intended to give developers a mental map of the system's components and their responsibilities. For guidelines on *how* to write code for this project, please refer to `CONVENTIONS.md`.

## Architectural Vision

`aico` is designed as a modular, stateless command-line application. The architecture prioritizes a clear separation of concerns, making the system testable, maintainable, and extensible. The core principle is that of a classic Unix tool: it receives input, processes it, and produces a predictable output, with all persistent state being explicit and transparent to the user.

## Component Breakdown

The application is composed of several distinct components, each with a clear role.

### Application Entrypoint & Orchestration

-   **Role:** This component is the front door to the application. It is responsible for initializing the command-line interface, discovering all built-in commands and external addons, and dispatching control to the appropriate command based on user input.
-   **Implementation:** This logic resides in `src/aico/main.py` and is built using the Typer framework.

### Data Modeling & Contracts

-   **Role:** This is the application's data backbone. It provides a single source of truth for the shape of all data, including session state, chat history, and internal data structures. It ensures type safety and guarantees that data loaded from files or APIs is valid.
-   **Implementation:** All data structures are defined as Pydantic models in `src/aico/lib/models.py`.

### State Persistence Layer

-   **Role:** This layer abstracts the loading and saving of session state. It provides a consistent interface for all commands, regardless of the underlying storage format. It supports both the legacy single-file `.ai_session.json` and the next-generation `historystore` architecture (sharded history + lightweight session pointers).
-   **Implementation:** The core logic is centralized in `src/aico/core/session_persistence.py`.
    -   A `SessionPersistence` protocol defines the `load()` and `save()` interface.
    -   A factory function, `get_persistence()`, inspects `.ai_session.json` to determine the storage format and returns the correct persistence backend.
    -   `LegacyJsonPersistence` handles the traditional single-file JSON format.
    -   `SharedHistoryPersistence` supports the new `historystore` format. Its `load()` reconstructs a legacy-compatible `SessionData` from a session view and sharded records (pre-sliced to the active window for fast status/log/token counting). Its `save()` supports write operations (append, single-edit, exclusions, history start, context/model updates) by default.
    -   For commands that need global pair IDs (e.g., `last`, `edit`, `undo`, `redo`, `set-history`), `SharedHistoryPersistence.load_full_history()` reconstructs the full history, ensuring indices are always resolved against the complete conversation.

### Command & Interaction Layer

-   **Role:** This component defines the public-facing API of the tool—the commands a user can run. Each command is responsible for handling its specific inputs and options and orchestrating calls to the other components to fulfill the user's request.
-   **Implementation:** Commands are organized in the `src/aico/commands/` directory. Each file corresponds to a single, top-level command (e.g., `last.py`, `status.py`, `log.py`). The application uses a flat command structure, avoiding nested command groups.

### Core Business Logic (The "Engines")

These are specialized components that handle the most complex processing tasks.

-   **LLM Interaction Engine:** This is the single entry point for all communication with the Large Language Model. It builds the full prompt (including system instructions, file context, and chat history), sends the request to the `litellm` library, and processes the response as a stream for real-time user feedback. It is also responsible for coordinating with the Diff & Patch Engine.
    -   **Implementation:** This logic is located in `src/aico/core/llm_executor.py`.

-   **Diff & Patch Engine:** This engine processes the raw text from the LLM to find and parse structured `SEARCH/REPLACE` blocks. It can apply these blocks to in-memory file content to generate both machine-readable unified diffs (for piping) and human-readable, rich-formatted output (for terminal display).
    -   **Implementation:** This is a dedicated, specialized component located in `src/aico/lib/diffing.py`.

### Extensibility Hooks (Addons)

-   **Role:** This component provides a mechanism for extending `aico` with custom commands. It discovers executable scripts in designated directories and integrates them into the main CLI. It passes session context to these scripts via an environment variable, allowing them to be written in any language.
-   **Implementation:** The discovery and execution logic is handled by `src/aico/addons.py`, using the `os.execvpe` system call to maintain a clean separation between the main application and the addon script.

## Data & Control Flow: Lifecycle of a Command

The components work together in a predictable sequence. The lifecycle of a typical `aico gen` command illustrates this flow:

1.  **Invocation:** The user's command is received by the **Entrypoint**, which routes it to the correct function in the **Command Layer**.
2.  **State Loading:** The command uses the **State Persistence Layer** to find and load the `.ai_session.json` file into memory as a structured Pydantic object. Most commands load only the active window; history-indexing commands that accept pair IDs use the full-history path to resolve indices globally.
3.  **Context Building:** The command reads the files specified in the session state from disk.
4.  **Prompt Construction:** The **LLM Interaction Engine** assembles the final prompt, combining system instructions, file contents, active chat history, and the new user instruction into a single request.
5.  **LLM Streaming & Parsing:** The request is sent to the LLM. As the response streams back:
    -   The **Diff & Patch Engine** live-parses the stream for `SEARCH/REPLACE` blocks.
    -   A live renderer displays conversational text and formatted diffs to the user in real-time.
6.  **State Saving:** After the full response is received, the user's prompt and the assistant's complete response are appended to the chat history. The **State Persistence Layer** then saves the updated session object back to disk atomically.
7.  **Final Output:** If the command is being piped (non-TTY), the **Diff & Patch Engine** generates a final, clean unified diff from the full response. The **Command Layer** then prints this diff to `stdout`. All diagnostic information has already been sent to `stderr`.
