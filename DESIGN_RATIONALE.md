# Design Rationale

This document captures the "why" behind significant architectural choices and the guiding philosophy of the `aico` project. It is intended to supplement `ARCHITECTURE.md` (the what) and `CONVENTIONS.md` (the how) by providing historical context and clarifying the reasoning behind non-obvious designs.

## Architectural Decision Records (ADRs)

These records explain the motivation and consequences of key architectural decisions.

### ADR-001: The Diff & Patch Engine Design

-   **Context:** The diffing engine (`src/diffing/parser.rs`) is the most complex component in the application. It has undergone several refactors.
-   **Decision:** We chose to implement a stateful "scan-and-yield" parser (`StreamParser`) using the `regex` crate instead of a simple string splitting approach.
-   **Rationale:** An early version based on splitting the LLM response by `File:` headers was fundamentally flawed: it consumed and discarded the newlines and any conversational text between `SEARCH/REPLACE` blocks. This resulted in lost context and corrupted display output. The `StreamParser` approach iterates through matches incrementally *without* discarding the text between them, ensuring every character of the LLM's raw response is preserved and processed correctly. This design is more complex but is far more robust against malformed LLM outputs and correctly preserves all conversational nuance. We use the `regex` crate for robustness and performance.

### ADR-002: The `passthrough` Feature for Advanced Scripting

-   **Context:** Advanced scripting workflows (like the `commit` addon) need to leverage the LLM without built-in prompt engineering.
-   **Decision:** We introduced a `--passthrough` flag available on core commands (`ask`, `gen`, `prompt`).
-   **Rationale:** The `--passthrough` flag is more than a "no-context" switch. When enabled, it bypasses `aico`'s prompt engineering: it does not inject file context, it does not add `<prompt>` or `<stdin_content>` tags, and it does not use alignment prompts. It creates a direct "pipe" to the LLM, sending the user's input verbatim. This gives addon authors and scripters control over the prompt.

### ADR-003: The `last --recompute` Feature for Context Correction

-   **Context:** An LLM may generate a perfect set of instructions that fail to apply only because the context was wrong (e.g., a file was missing). We needed a way for the user to recover from this.
-   **Decision:** The `last` command includes a `--recompute` flag.
-   **Rationale:** The primary purpose of `last --recompute` is to **fix broken context**. It allows a user to run an instruction, see it fail, correct the session context (`aico add ...`), and then re-apply the *exact same instruction* to the new, correct state. To serve this purpose reliably, `recompute` will *always* use the full, current session context, even if the original command was run with `--passthrough`. This makes it a predictable and powerful tool for recovering from context-related failures.

### ADR-004: Unified Parsing and Structured Display Persistence

-   **Context:** A series of rendering bugs revealed systemic issues. The live renderer showed garbled output for failed patches, and the `aico last` command showed the same garbled output for historical failed patches because the structural information from parsing was being lost during session saving.
-   **Decision:** We made two related architectural changes:
    1.  The `StreamParser` in `src/diffing/parser.rs` was made the **single source of truth** for all LLM output parsing (live rendering, final output, `last --recompute`).
    2.  The result of this parsing is stored in the session history not as a pre-rendered string, but as a structured list of display items (`Vec<DisplayItem>`).
-   **Rationale:**
    -   **Unified Parsing:** The initial bugs stemmed from having duplicated and slightly different parsing logic in multiple places. By centralizing all parsing into one stateful struct, we guarantee that the live view, the piped output, and the historical view (`aico last`) are all derived from the exact same logic, eliminating an entire class of rendering inconsistencies.
    -   **Structured Persistence:** The `aico last` bug was caused by "stringly-typed" persistence—flattening structured data (like conversational text, diffs, and warnings) into a single string for storage, thereby losing the information needed for correct rendering later. Storing the output as a serialized list of structs (`DisplayItem`) preserves this structure.
    -   **Backward Compatibility:** The session model (`DerivedContent`) uses `Option<Vec<DisplayItem>>`. This allows the `last` command to correctly render new, structured history while seamlessly falling back to text-only rendering for legacy sessions, ensuring a smooth upgrade path.

### ADR-005: Flat, Verb-Driven CLI Structure

-   **Context:** The CLI initially had nested command groups like `aico history view` and `aico tokens`. This is a common pattern for complex applications, but it was found to hide functionality and add an unnecessary layer of abstraction for a command-line tool.
-   **Decision:** We dissolved the `history` and `tokens` command groups, promoting their functionality to top-level, verb-driven commands (e.g., `aico status`, `aico log`). We also eliminated redundant commands like `history reset` whose functionality was a subset of another command (`set-history 0`).
-   **Rationale:** This decision was driven by the core philosophy of making `aico` feel like a classic, composable Unix tool (see `CONVENTIONS.md`). A flat structure improves discoverability, as all commands are visible in the top-level `aico --help` output. It simplifies command memorability (e.g., "what's the git status?" -> `git status`; "what's the aico status?" -> `aico status`) and makes the tool feel more direct and less like a "managed application."

### ADR-006: Unified Pair-Based History Indexing

-   **Context:** Commands that interact with the chat history (`last`, `undo`, `set-history`) need a way to reference specific points in the conversation. Different indexing schemes were possible (e.g., by raw message index, by pair index), creating a risk of an inconsistent and confusing user experience.
-   **Decision:** We explicitly standardized on a **message pair** (one user prompt and its corresponding assistant response) as the atomic unit of the conversation. The `aico log` command was designed to display a clear `ID` for each pair. All other history commands (`last`, `undo`, `set-history`) were unified to consume this exact pair ID as their primary argument.
-   **Rationale:** This provides a consistent and logical mental model for the user. They learn one concept—the pair ID from `aico log`—and can apply it everywhere, reducing cognitive load. It avoids the ambiguity of a raw message index where a user might accidentally target their own prompt when they meant to target the AI's response or vice-versa. Treating the prompt/response as a single, atomic unit is more intuitive for operations like "undoing" a conversational turn.

### ADR-007: Offline-First Model Metadata

-   **Context:** To provide cost estimates and context window warnings (`aico status`), the tool needs up-to-date model pricing data.
-   **Decision:** We implemented a lazy-loading, file-based cache in `~/.cache/aico/` that fetches pricing data from OpenRouter/LiteLLM APIs periodically (TTL 14 days) using `src/model_registry.rs`.
-   **Rationale:** This ensures `aico` remains fast and usable offline. We avoid blocking the CLI startup on network calls. If the cache is missing or the network is down, the tool degrades gracefully (showing no cost info) rather than crashing or hanging.

### ADR-008: The Shared-History Architecture (Pointer-View-Store)

-   **Context:** As sessions grow, the legacy single-file JSON format (`.ai_session.json`) becomes inefficient to read/write. Furthermore, users requested git-like features: the ability to "branch" a conversation to try different solutions without duplicating the entire history data.
-   **Decision:** We implemented a three-tier storage architecture:
    1.  **Pointer:** A tiny `.ai_session.json` file that contains only a reference to the active view.
    2.  **View:** A lightweight JSON file (in `.aico/sessions/`) that defines a "branch." It holds metadata (model, context files) and an ordered list of integer IDs referencing messages in the store.
    3.  **Store:** An append-only, sharded log (in `.aico/history/*.jsonl`) that holds the actual immutable message content.
-   **Rationale:**
    -   **Performance:** Appending a message requires only writing to the current 10k-line shard and updating the lightweight view, making I/O constant-time rather than linear to session size.
    -   **Branching:** Creating a new branch is cheap (creating a small JSON view) because the heavy message content is referenced by ID, not copied.
    -   **Immutability:** Message content is never overwritten, only appended. Edits create new records, preserving a traceable lineage of the conversation.

### ADR-009: Process-Based Addon System

-   **Context:** Users need to extend `aico` with custom workflows (e.g., generating commits, summarizing history), but we wanted to avoid the complexity and fragility of a plugin API that runs arbitrary user code inside the main process.
-   **Decision:** We implemented addons as **executable scripts** (subprocesses) rather than internal plugins. We use `std::process::Command` (and `exec` on Unix systems) to hand over control to the addon.
-   **Rationale:**
    -   **Isolation:** Addons cannot crash the main `aico` process or corrupt its memory.
    -   **Language Agnostic:** Users can write addons in Bash, Python, Ruby, or Rust; `aico` simply executes them.
    -   **Simplicity:** The "API" is simply the environment variables (like `AICO_SESSION_FILE`) passed to the subprocess. This adheres to the Unix philosophy of small tools working together.

### ADR-010: "Ground Truth" Context Anchoring

-   **Context:** As history grows, LLMs can "forget" the state of files or hallucinate that they have applied patches that were merely discussed.
-   **Decision:** We inject the file context wrapped in XML tags (`<context>`) followed by a **forced assistant response** (pre-filled message) stating: *"I have read the current file state. I will use this block as the ground truth..."*
-   **Rationale:**
    -   **Combatting Hallucination:** By forcing the model to "acknowledge" the read, we significantly reduce the likelihood of it relying on outdated code snippets found earlier in the chat history.
    -   **Turn Alignment:** Inserting a fake assistant response maintains the strict User/Assistant turn structure required by the API while effectively making the file context "stick" more strongly than a system prompt alone.
    -   **Caching:** The structured prompt topology (System → Context/Anchor → History → Alignment → Final) enables effective prompt caching in supported models/providers by isolating stable context prefixes.

## Project Philosophy & Vision

### Error Handling Philosophy: Fail Fast

Our approach to external API failures (e.g., LLM rate limits, invalid keys) is to treat them as fatal. `aico` will attempt one well-defined action; if it fails, it reports the error and exits.

- **Rationale:** This aligns with the "tool, not an agent" philosophy. The tool is predictable. By exiting on failure, it reports the error and stops. We do not implement retry logic internally to maintain transparency.

### Future Vision and The "Anti-Roadmap"

The vision for `aico` is to keep it a lean, focused, and user-controlled tool. Future enhancements should focus on improving the core experience (e.g., better diffing, more intuitive commands).

-   **Delegation to Addons:** More complex automation and features that blur the line between "tool" and "agent" are explicitly delegated to the addon system. Users who desire more automation can build it themselves using `aico` as the core engine.
-   **The Anti-Roadmap:** This vision defines what `aico` will *not* become. There are no plans to have it execute shell commands it generates, autonomously decide which files to edit, or take other agent-like actions. Its purpose is to generate text and diffs, leaving the final decision of execution to the developer.
