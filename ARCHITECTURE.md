# `aico` Architecture

This document provides a high-level overview of the `aico` codebase architecture. It provides a mental map of the system's components. For guidelines on *how* to write code for this project, refer to `CONVENTIONS.md`.

## Architectural Vision

`aico` is designed as a modular, stateless command-line application. The architecture prioritizes a clear separation of concerns, making the system testable, maintainable, and extensible. The core principle is that of a classic Unix tool: it receives input, processes it, and produces a predictable output, with all persistent state being explicit and transparent to the user.

Originally prototyped in Python, `aico` has been rewritten in **Rust** to provide a single, dependency-free binary, strict type safety, and instant startup times crucial for CLI ergonomics.

## Component Breakdown

The application is composed of several distinct components, each with a clear role.

### Application Entrypoint & Orchestration

-   **Role:** This component is the front door to the application. It is responsible for initializing the command-line interface, parsing arguments, discovering addons, and dispatching control to the appropriate command handler.
-   **Implementation:** This logic resides in `src/main.rs`. It uses the `clap` crate for declarative argument parsing and subcommand dispatch.

### Data Modeling & Contracts

-   **Role:** This is the application's data backbone. It provides a single source of truth for the shape of all data, including session state, chat history, and internal data structures. It ensures strict type safety and guarantees that data loaded from files or APIs is valid.
-   **Implementation:** All data structures are defined as Rust structs and enums in `src/models.rs`. We use `serde` for serialization/deserialization.

### State Persistence Layer

-   **Role:** This layer manages the loading, saving, and surgical modification of session state. It provides a consistent interface for all commands to interact with the conversation history and metadata.
-   **Implementation:** The core logic is centralized in the `Session` struct in `src/session.rs`. It exclusively supports the `historystore` architecture:
    -   **Pointer:** The `.ai_session.json` file in the project root acts as a pointer to the active session view.
    -   **View:** Lightweight JSON files in `.aico/sessions/` store session-specific metadata (model, context files, excluded pairs) and a list of global message IDs.
    -   **Store:** An append-only, sharded log in `.aico/history/` contains the immutable message content (handled by `src/historystore/store.rs`).
    -   The `Session` struct provides high-level methods for appending message pairs, surgically fetching specific messages by index, and updating view-level metadata like exclusions or context boundaries.

### Command & Interaction Layer

-   **Role:** This component defines the public-facing API of the tool—the commands a user can run. Each command is responsible for handling its specific inputs and options and orchestrating calls to the other components to fulfill the user's request.
-   **Implementation:** Commands are organized in the `src/commands/` directory. Each module corresponds to a specific command logic (e.g., `last.rs`, `status.rs`, `log.rs`, `llm_shared.rs`). The application uses a flat command structure, avoiding nested command groups.

### Core Business Logic (The "Engines")

These components handle complex processing tasks.

-   **LLM Interaction Engine:** The entry point for all LLM communication. It assembles the prompt using a **Two-Tiered Chronological Context** strategy to minimize hallucinations and maintain a strict "Ground Truth" for source code.
    -   **Implementation:** This logic is located in `src/llm/executor.rs`.
    -   **Context Splicing:** Instead of appending context at the end of the prompt, `aico` categorizes files based on their modification time relative to the **start of the active conversation window** (logic in `session.rs`):
        1.  **Static Block (Baseline):** Files unmodified since the start of the current chat window are placed at the very beginning of the prompt to establish the baseline "Ground Truth."
        2.  **Floating Block (Update):** Files modified during the session are bundled into a single update block.
        3.  **Chronological Injection:** The Floating block is "spliced" into the chat history at the specific point in time the manual changes occurred (`max(mtime)` of the changed files).
    -   **Ground Truth Anchoring:** Every context block is followed by a forced assistant response (an "Anchor") where the model explicitly acknowledges the provided XML as the absolute source of truth.

-   **Provider Client & Model Info:** This layer abstracts the differences between API providers.
    -   **Client:** Handles HTTP communication via `reqwest`. Located in `src/llm/client.rs`. It parses the model string prefix (`openai/` vs `openrouter/`) to determine the base URL and required headers.
    -   **Model Metadata Service:** Fetches and caches model capabilities (context window size) and pricing data to `~/.cache/aico/`. This allows `aico status` to provide cost estimates without blocking on network calls. Located in `src/model_registry.rs`.

-   **Diff & Patch Engine:** Processes raw text from the LLM to find and parse structured `SEARCH/REPLACE` blocks. It applies these blocks to in-memory file content to generate machine-readable unified diffs (for piping) and formatted output (for terminal display).
    -   **Implementation:** This is a dedicated, specialized component located in `src/diffing/parser.rs`. It implements a state machine (`StreamParser`) that processes text chunks incrementally as they arrive from the network.

### Extensibility Hooks (Addons)

-   **Role:** This component provides a mechanism for extending `aico` with custom commands. It discovers executable scripts in designated directories and integrates them into the main CLI. It passes session context to these scripts via an environment variable (`AICO_SESSION_FILE`), allowing them to be written in any language.
-   **Implementation:** The discovery and execution logic is handled by `src/addons.rs`. It uses `std::process::Command` (and `exec` on Unix systems) to hand over control to the addon script.

## Data & Control Flow: Lifecycle of a Command

The components work together in a predictable sequence. The lifecycle of an `aico gen` command illustrates this flow:

1.  **Invocation:** The binary starts, `main.rs` parses arguments via `clap`, and routes execution to `commands/generate.rs` (which calls `llm_shared.rs`).
2.  **State Loading:** The command uses `Session::load_active` (`src/session.rs`) to load the `.ai_session.json` file. This deserializes the JSON state into the `Session` struct.
3.  **Context Building:** The session reads the files specified in the session state from disk into memory.
4.  **Prompt Construction:** The **LLM Interaction Engine** (`src/llm/executor.rs`) assembles the final prompt, combining system instructions, file contents (using the splicing strategy), active chat history, and the new user instruction.
5.  **LLM Streaming & Parsing:** The `LlmClient` initializes an asynchronous HTTP stream. As the response streams back:
    -   The **Diff & Patch Engine** (`src/diffing/parser.rs`) live-parses the incoming bytes for `SEARCH/REPLACE` blocks.
    -   A live renderer (`src/ui/live_display.rs`) displays conversational text and formatted diffs in real-time to the TTY.
6.  **State Saving:** After the stream concludes, the user's prompt and the assistant's complete response are appended to the chat history via `Session::append_pair`. The **State Persistence Layer** saves the updated view back to disk atomically.
7.  **Final Output:** If the command is being piped (non-TTY), the final unified diff generated by the parser is printed to `stdout`. All diagnostic information (costs, token usage) is printed to `stderr`.
