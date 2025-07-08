# Design Rationale

This document captures the "why" behind significant architectural choices and the guiding philosophy of the `aico` project. It is intended to supplement `ARCHITECTURE.md` (the what) and `CONVENTIONS.md` (the how) by providing historical context and clarifying the reasoning behind non-obvious designs.

## Architectural Decision Records (ADRs)

These records explain the motivation and consequences of key architectural decisions.

### ADR-001: The Diff & Patch Engine Design

-   **Context:** The `diffing.py` engine is the most complex component in the application. It has undergone several refactors.
-   **Decision:** We chose to implement a "scan-and-yield" parser using `regex.finditer()` instead of a simpler `string.split()` approach.
-   **Rationale:** An early version based on splitting the LLM response by `File:` headers was fundamentally flawed: it consumed and discarded the newlines and any conversational text between `SEARCH/REPLACE` blocks. This resulted in lost context and corrupted display output. The `finditer` approach iterates through matches *without* discarding the text between them, ensuring every character of the LLM's raw response is preserved and processed correctly. This design is more complex but is far more robust against malformed LLM outputs and correctly preserves all conversational nuance.

### ADR-002: The `passthrough` Feature for Advanced Scripting

-   **Context:** We needed a way for advanced scripting workflows (like the `commit` addon) to leverage the LLM without `aico`'s built-in prompt engineering.
-   **Decision:** We introduced a `--passthrough` flag available on core commands (`ask`, `gen`, `prompt`).
-   **Rationale:** The `--passthrough` flag is more than just a "no-context" switch. When enabled, it bypasses *all* of `aico`'s prompt engineering: it does not inject file context, it does not add `<prompt>` or `<stdin_content>` XML-like tags, and it does not use the alignment prompts. It creates a clean, direct "pipe" to the LLM, sending the user's input verbatim. This gives addon authors and scripters full control over the prompt when `aico`'s default formatting is not desired.

### ADR-003: The `last --recompute` Feature for Context Correction

-   **Context:** An LLM may generate a perfect set of instructions that fail to apply only because the context was wrong (e.g., a file was missing). We needed a way for the user to recover from this.
-   **Decision:** The `last` command includes a `--recompute` flag.
-   **Rationale:** The primary purpose of `last --recompute` is to **fix broken context**. It allows a user to run an instruction, see it fail, correct the session context (`aico add ...`), and then re-apply the *exact same instruction* to the new, correct state. To serve this purpose reliably, `recompute` will *always* use the full, current session context, even if the original command was run with `--passthrough`. This makes it a predictable and powerful tool for recovering from context-related failures.

### ADR-004: Unified Parsing and Structured Display Persistence

-   **Context:** A series of rendering bugs revealed systemic issues. The live renderer showed garbled output for failed patches, and the `aico last` command showed the same garbled output for historical failed patches because the structural information from parsing was being lost during session saving.
-   **Decision:** We made two related architectural changes:
    1.  The `process_llm_response_stream` generator in `diffing.py` was made the **single source of truth** for all LLM output parsing (live rendering, final output, `last --recompute`).
    2.  The result of this parsing is stored in the session history not as a pre-rendered string, but as a structured list of display items (`list[DisplayItem]`).
-   **Rationale:**
    -   **Unified Parsing:** The initial bugs stemmed from having duplicated and slightly different parsing logic in multiple places. By centralizing all parsing into one stateful generator, we guarantee that the live view, the piped output, and the historical view (`aico last`) are all derived from the exact same logic, eliminating an entire class of rendering inconsistencies.
    -   **Structured Persistence:** The `aico last` bug was caused by "stringly-typed" persistence—flattening structured data (like conversational text, diffs, and warnings) into a single string for storage, thereby losing the information needed for correct rendering later. Storing the output as a `list[{"type": ..., "content": ...}]` preserves this structure.
    -   **Backward Compatibility:** The session model for the persistence field (`derived.display_content`) uses the type `list[DisplayItem] | str | None`. This allows the `last` command to correctly render new, structured history while seamlessly falling back to the old rendering behavior for session files created before this change, ensuring a smooth and non-breaking upgrade for users.

## Project Philosophy & Vision

### Dependency Rationale: Why `litellm`?

`litellm` is a hard dependency used for all LLM interactions. This was a pragmatic choice.

-   **Pros:** It provides crucial, non-trivial functionality out of the box: provider abstraction (supporting OpenAI, Anthropic, OpenRouter, etc.), token counting, and cost estimation. Implementing this ourselves would be a significant effort.
-   **Cons:** Its codebase is not as clean as our project's standards, and its type hinting is incomplete, requiring us to create defensive boundaries.
-   **Conclusion:** We accept the trade-off. The immediate benefits of its features outweigh the cost of managing the dependency.

### Error Handling Philosophy: Fail Fast

Our approach to external API failures (e.g., LLM rate limits, invalid keys) is to treat them as fatal. `aico` will attempt one well-defined action; if it fails, it reports the error and exits.

-   **Rationale:** This aligns with the "tool, not an agent" philosophy. The tool should be predictable. By exiting on failure, it returns control to the user, who can then decide whether to retry, change API keys, or take other action. We do not implement complex retry logic internally, as this would make the tool's behavior less transparent.

### Future Vision and The "Anti-Roadmap"

The vision for `aico` is to keep it a lean, focused, and user-controlled tool. Future enhancements should focus on improving the core experience (e.g., better diffing, more intuitive commands).

-   **Delegation to Addons:** More complex automation and features that blur the line between "tool" and "agent" are explicitly delegated to the addon system. Users who desire more automation can build it themselves using `aico` as the core engine.
-   **The Anti-Roadmap:** This vision defines what `aico` will *not* become. There are no plans to have it execute shell commands it generates, autonomously decide which files to edit, or take other agent-like actions. Its purpose is to generate text and diffs, leaving the final decision of execution to the developer.
