# `aico` Architecture

This document provides a high-level overview of the `aico` codebase architecture. It provides a mental map of the system's components. For guidelines on *how* to write code for this project, refer to `CONVENTIONS.md`.

## Architectural Vision

`aico` is designed as a modular, stateless command-line application. The architecture prioritizes a clear separation of concerns, making the system testable, maintainable, and extensible. The core principle is that of a classic Unix tool: it receives input, processes it, and produces a predictable output, with all persistent state being explicit and transparent to the user.

## Component Breakdown

The application is composed of several distinct components, each with a clear role.

### Application Entrypoint & Orchestration

-   **Role:** This component is the front door to the application. It is responsible for initializing the command-line interface, discovering all built-in commands and external addons, and dispatching control to the appropriate command based on user input.
-   **Implementation:** This logic resides in `src/aico/main.py` and is built using the Typer framework.

### Data Modeling & Contracts

-   **Role:** This is the application's data backbone. It provides a single source of truth for the shape of all data, including session state, chat history, and internal data structures. It ensures type safety and guarantees that data loaded from files or APIs is valid through JIT-compiled validation.
-   **Implementation:** All data structures are defined as `msgspec.Struct` models in `src/aico/models.py`.

### State Persistence Layer

-   **Role:** This layer manages the loading, saving, and surgical modification of session state. It provides a consistent interface for all commands to interact with the conversation history and metadata.
-   **Implementation:** The core logic is centralized in the `Session` class in `src/aico/session.py`. It exclusively supports the `historystore` architecture:
    -   **Pointer:** The `.ai_session.json` file in the project root acts as a pointer to the active session view.
    -   **View:** Lightweight JSON files in `.aico/sessions/` store session-specific metadata (model, context files, excluded pairs) and a list of global message IDs.
    -   **Store:** An append-only, sharded log in `.aico/history/` contains the immutable message content.
    -   The `Session` class provides high-level methods for appending message pairs, surgically fetching specific messages by index, and updating view-level metadata like exclusions or context boundaries.

### Command & Interaction Layer

-   **Role:** This component defines the public-facing API of the tool—the commands a user can run. Each command is responsible for handling its specific inputs and options and orchestrating calls to the other components to fulfill the user's request.
-   **Implementation:** Commands are organized in the `src/aico/commands/` directory. Each file corresponds to a single, top-level command (e.g., `last.py`, `status.py`, `log.py`). The application uses a flat command structure, avoiding nested command groups.

### Core Business Logic (The "Engines")

These components handle processing tasks.

-   **LLM Interaction Engine:** The entry point for all LLM communication. It assembles the prompt using a **Two-Tiered Chronological Context** strategy to minimize hallucinations and maintain a strict "Ground Truth" for source code.
    -   **Implementation:** This logic is located in `src/aico/llm/executor.py`.
    -   **Context Splicing:** Instead of appending context at the end of the prompt, `aico` categorizes files based on their modification time relative to the **start of the active conversation window** (the timestamp of the first message included in the current prompt):
        1.  **Static Block (Baseline):** Files unmodified since the start of the current chat window are placed at the very beginning of the prompt to establish the baseline "Ground Truth."
        2.  **Floating Block (Update):** Files modified during the session are bundled into a single update block.
        3.  **Chronological Injection:** The Floating block is "spliced" into the chat history at the specific point in time the manual changes occurred (`max(mtime)` of the changed files). This allows the model to "see" the code evolve in order.
    -   **Ground Truth Anchoring:** Every context block is followed by a forced assistant response (an "Anchor") where the model explicitly acknowledges the provided XML as the absolute source of truth.

-   **Provider Router & Model Info:** This layer abstracts the differences between API providers.
    -   **Router:** Determines whether to route requests to OpenAI direct or OpenRouter based on the model string prefix (`openai/` vs `openrouter/`) and configures the HTTP client accordingly. Located in `src/aico/llm/router.py`.
    -   **Model Metadata Service:** Fetches and caches model capabilities (context window size) and pricing data to `~/.cache/aico/`. This allows `aico status` to provide cost estimates without blocking on network calls or requiring a heavy dependency. Located in `src/aico/model_registry.py`.

-   **Diff & Patch Engine:** Processes raw text from the LLM to find and parse structured `SEARCH/REPLACE` blocks. It applies these blocks to in-memory file content to generate machine-readable unified diffs (for piping) and formatted output (for terminal display).
    -   **Implementation:** This is a dedicated, specialized component located in `src/aico/diffing/stream_processor.py`.

### Extensibility Hooks (Addons)

-   **Role:** This component provides a mechanism for extending `aico` with custom commands. It discovers executable scripts in designated directories and integrates them into the main CLI. It passes session context to these scripts via an environment variable, allowing them to be written in any language.
-   **Implementation:** The discovery and execution logic is handled by `src/aico/addons.py`, using the `os.execvpe` system call to maintain a clean separation between the main application and the addon script.

## Data & Control Flow: Lifecycle of a Command

The components work together in a predictable sequence. The lifecycle of an `aico gen` command illustrates this flow:

1.  **Invocation:** The command is received by the **Entrypoint**, which routes it to the function in the **Command Layer**.
2.  **State Loading:** The command uses the **State Persistence Layer** to load the `.ai_session.json` file into memory as a structured `msgspec.Struct` object. Commands load the active window; history-indexing commands that accept pair IDs use the full-history path to resolve indices globally.
3.  **Context Building:** The command reads the files specified in the session state from disk.
4.  **Prompt Construction:** The **LLM Interaction Engine** assembles the final prompt, combining system instructions, file contents, active chat history, and the new user instruction into a single request.
5.  **LLM Streaming & Parsing:** The **Provider Router** initializes the API client. As the response streams back:
    -   The **Diff & Patch Engine** live-parses the stream for `SEARCH/REPLACE` blocks.
    -   A live renderer displays conversational text and formatted diffs in real-time.
6.  **State Saving:** After the full response is received, the user's prompt and the assistant's complete response are appended to the chat history. The **State Persistence Layer** then saves the updated session object back to disk atomically.
7.  **Final Output:** If the command is being piped (non-TTY), the **Diff & Patch Engine** generates a final, clean unified diff from the full response. The **Command Layer** then prints this diff to `stdout`. All diagnostic information has already been sent to `stderr`.
