## Example workflow: Specification-Driven Development

aico is unopinionated, but it becomes most powerful when paired with strict project conventions.

This document outlines a production workflow used in environments where architectural integrity and strict type safety are required. It enforces a **Specification-First** process where implementation code is never generated until a behavioral specification (MDG) is defined and verified.

[Markdown with Gherkin (MDG)](https://github.com/cucumber/gherkin/blob/main/MARKDOWN_WITH_GHERKIN.md) is a superset of GitHub Flavored Markdown that allows embedding executable Gherkin scenarios directly into rich documentation (.feature.md), a format we prefer because LLMs are exceptionally capable at reading and writing Markdown structure compared to rigid whitespace-sensitive formats.

This workflow illustrates aico's strength as a composable tool rather than an opinionated agent. Unlike assistants that abstract away the process, aico gives the developer granular control over context and history. This allows teams to enforce rigid project conventions—such as layered architecture boundaries and specific naming rules—directly through the tool's usage patterns. By explicitly managing what the model sees (add/drop) and how it remembers (edit), this workflow turns the LLM from a chaotic generator into a compliant architectural engine.

### **The Philosophy**

1. **Spec First, Code Second:** Implementation never begins without a Markdown Gherkin (MDG) specification.
2. **Rich, Bounded Context:** Unlike "minimalist" context strategies, we aim to provide extensive context (up to ~40-50k tokens). We include similar services, controllers, and repositories to give the LLM ample "one-shot" examples, but we respect this upper bound to ensure reasoning quality stays sharp.
3. **Mandatory Conventions:** CONVENTIONS.md is **always** in context. It is the absolute authority on file layout, modern Python syntax, and linting rules.
4. **Zero-Tolerance for Hallucination:** If the AI mistakes a name, we fix its memory (edit) rather than working around it.

## **The "Prompt Language" Technique**

This workflow relies on a set of shorthand prompts defined in CONVENTIONS.md.

**How it works:** These are **not** hardcoded CLI commands. They are simple text strings that the LLM interprets based on the CONVENTIONS.md file in its context. Because the LLM "reads" the conventions, it knows exactly how to behave when it sees brst or mkgreen.

### **Prompt Cheat-Sheet**

| Prompt      | Phase    | Meaning                                                                                                  |
| :---------- | :------- | :------------------------------------------------------------------------------------------------------- |
| **brst**    | Planning | **Brainstorm.** Summarize understanding as a list, then ask numbered questions. **Never** generate code. |
| **yasss**   | Planning | **Confirm.** Check for understanding. If clear, return the plan. If unclear, ask questions.              |
| **mkgold**  | Spec     | **Make Golden.** Generate the "golden path" MDG scenario. Start with the simplest imaginable scenario.   |
| **mkgreen** | Exec     | **Make Green.** Implement the minimal code required to pass the test/spec.                               |
| **mkcurl**  | Verify   | **Make Curl.** Return a one-line curl command to verify the feature on localhost.                        |

### **The Workflow Lifecycle**

#### **1. The Alignment Phase (Brainstorming)**

We are never eager to generate code. We start by strictly aligning on the feature's intent.

1. **Load Reference Material:** Context is crucial even for the spec. We add similar controllers and services so our brainstorming session builds upon existing project patterns.

   ```sh
   aico add app/services/similar_service.py
   ```

2. **Initial Brainstorm:**
   We ask the LLM to process the request. It must return a summary of its understanding followed by numbered questions.

   ```sh
   aico ask "We need to add a 'Apply Voucher' endpoint that validates expiration dates. brst"
   ```

3. **Iterative Alignment:**
   We answer the questions and run brst cycles (usually 1-2 times) until we feel fully aligned.

   *Definition of Ready:* You are done aligning when:

   - The AI's summary matches your architectural vision.
   - The AI stops asking fundamental questions about "how" or "what".
   - You feel confident that the "Plan" is actionable.

4. **Confirmation:**
   Once the understanding is solid, we lock it in.

   ```sh
   # Answering the specific questions the AI asked in the previous turn
   aico ask "1: yes, 2: agree. yasss"
   ```

#### **2. The Specification Phase**

Only after yasss do we generate the behavior specification.

1. **Draft the Golden Path:**
   We ask the AI to generate the simplest "happy path" scenario for the feature.
   ```sh
   aico gen "mkgold"
   ```
2. **Review and Apply:**
   ```sh
   aico last | patch -p1
   ```

#### **3. Context Enrichment**

Before generating implementation code, we ensure the context is complete.

- **Manual Addition:** aico does not automatically context-load files it generated. We **must** manually add the MDG we just created.
- **Verify Reference Material:** Ensure the "similar" services/controllers added in Phase 1 are still relevant.
- **Constraint Check:** We check aico status. If we are nearing the **40-50k token limit**, we drop reference files that are no longer needed (e.g., example code that has already served its purpose).

```sh
aico add features/apply_voucher.feature.md
aico status
# Optional: aico drop app/services/old_example.py
```

#### **4. The "Red" Phase (Manual Verification)**

We strictly adhere to the Red-Green loop. Before asking the AI to write code, we ensure we have a failing test.

1. **Run Tests:** Execute the test suite targeting the new feature file.
2. **Verify Failure:** Confirm it fails for the expected reason (missing implementation).

#### **5. The Execution Phase**

With the MDG defining *what* to do, and similar files defining *how* to do it, we generate the code.

1. **Generate Code:**
   The mkgreen prompt tells the AI: "Read the MDG, look at the project patterns, and implement the missing logic to make this spec pass."
   ```sh
   aico gen "mkgreen" # Implement the feature matching the MDG.
   ```
2. **Review & The "Lobotomy" Strategy:**
   Critical Step: Before piping to patch, we review the output (aico last).
   If the AI violates a naming convention (e.g., VoucherPayload instead of VoucherDto), **we fix the history first**. This prevents the "revert-and-retry" dance and stops the AI from hallucinating the wrong name in future turns.
   ```sh
   # 1. Open the response in editor and fix the name in the diff block
   aico edit

   # 2. Apply the corrected patch
   aico last | patch -p1
   ```

#### **6. Verification and Reset**

Once the feature is complete:

1. **Verification:**
   We ask for a one-liner to verify the work.
   ```sh
   aico ask "mkcurl"
   ```
   *(We copy-paste the output to verify the endpoint)*
2. **The Clean Slate:**
   We never reuse a "polluted" session for a new feature. We use the summarize addon to archive the history and reset the context.
   ```sh
   aico summarize
   ```
