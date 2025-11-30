# Example Workflow: Specification-Driven Development

`aico` is unopinionated by design, but it becomes incredibly powerful when paired with a strong set of project conventions.

This guide walks through a production-grade workflow used in strict environments. The goal here isn't just to generate code fast, but to generate **correct, architecturally sound code** by forcing a specific order of operations: **Spec First, Code Second.**

In this workflow, we treat `aico` not as a chatty assistant, but as a precise engine that reads our `CONVENTIONS.md` and executes architectural instructions.

## The Setup: "Prompt Engineering" via Conventions

Instead of typing long prompts like *"Please look at the architecture and brainstorm ideas..."* every time, we define shorthand commands in our project's `CONVENTIONS.md` file. Because `aico` sees that file in its context, it "learns" these commands instantly.

Here is the cheat sheet we use for this workflow:

| Command       | Phase    | What it tells `aico` to do                                                                                                             |
| ------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **`brst`**    | Planning | **Brainstorm.** Don't write code yet. Read the request, summarize your understanding, and ask numbered questions to clarify ambiguity. |
| **`yasss`**   | Planning | **Confirm.** "Yes, that plan is correct." If you are ready, output the final plan. If not, ask more questions.                         |
| **`mkgold`**  | Spec     | **Make Golden.** Generate a "Golden Path" Gherkin scenario (MDG) that describes the feature's successful behavior.                     |
| **`mkgreen`** | Exec     | **Make Green.** Write the minimal implementation code required to make the spec pass.                                                  |
| **`mkcurl`**  | Verify   | **Make Curl.** Give me a one-line `curl` command to test this endpoint on localhost.                                                   |

## Walkthrough: Building an "Apply Voucher" Feature

Let's say we need to add an endpoint to apply a discount voucher. Here is how we move from idea to shipped code.

### Phase 1: Alignment (The "brst" Loop)

We never jump straight to code generation. First, we ensure the AI understands the architectural boundaries.

1. **Load Reference Material:**
   Give the AI examples of how you write code in this project.

   ```sh
   aico add app/services/similar_service.py app/controllers/similar_controller.py
   ```

2. **Start Brainstorming:**
   Ask the AI to brainstorm (`brst`). It will read your conventions and know that `brst` means "ask questions first."

   ```sh
   aico ask "We need a new 'Apply Voucher' endpoint. It should validate dates and check usage limits. brst"
   ```

3. **Refine the Plan:**
   The AI will reply with questions like *"Should we validate the voucher code case-insensitively?"* or *"Where is the usage limit stored?"*.

   Answer these questions in the chat.

   ```sh
   aico ask "1. Yes, case-insensitive. 2. Stored in Redis. brst"
   ```

4. **Lock it in:**
   When the AI's summary matches your vision, confirm it.

   ```sh
   aico ask "yasss"
   ```

### Phase 2: The Specification

Now that we agree on *what* we are building, we generate a formal specification. We use [Markdown with Gherkin (MDG)](https://github.com/cucumber/gherkin/blob/main/MARKDOWN_WITH_GHERKIN.md) because LLMs are excellent at reading and producing it.

1. **Generate the Spec:**

   ```sh
   aico gen "mkgold"
   ```

   *Result:* `aico` generates a new file `features/apply_voucher.feature.md` describing the happy path.

2. **Review and Apply:**

   ```sh
   aico last | patch -p1
   ```

3. **Context Swap:**
   Now that the spec exists, we add it to the context. This file is now the **source of truth** for the implementation.

   ```sh
   aico add features/apply_voucher.feature.md
   ```

### Phase 3: The Red-Green Loop

We now have a failing test (the spec) and a plan. It's time to generate the implementation.

1. **Generate the Code:**
   We use the `mkgreen` shorthand. This tells `aico`: *"Read the Gherkin spec we just added, look at the `similar_service.py` for coding style, and write the implementation."*

   ```sh
   aico gen "mkgreen"
   ```

2. **The "Lobotomy" Review:**
   Before applying the code, check the diff (`aico last`). If `aico` hallucinated a variable name or violated a convention, **do not fix it in your editor yet.** Fix it in the chat history using `aico edit`.

   *Why?* If you fix it silently in the code, `aico` still "remembers" generating the wrong name and might hallucinate it again in the next turn. By editing the history, you effectively "lobotomize" the error, ensuring the AI learns from the correction.

3. **Apply the Code:**

   ```sh
   aico last | patch -p1
   ```

### Phase 4: Verify and Clean Up

1. **Manual Verification:**
   Ask for a quick verification command.

   ```sh
   aico ask "mkcurl"
   ```

   Paste the resulting curl command into your terminal to confirm it works.

2. **Summarize and Reset:**
   LLM sessions get "polluted" over time as context grows. Once the feature is merged, use the `summarize` addon to archive the discussion and clear the token window for the next task.

   ```sh
   aico summarize
   ```

## Why this works

- **Bounded Context:** We manually `add` and `drop` files to ensure the AI focuses only on relevant code, keeping token costs low and reasoning sharp.

- **Zero Hallucination Tolerance:** By using `aico edit` to fix mistakes in the history, we prevent the model from spiraling into bad patterns.

- **Predictability:** By relying on abbreviations we defined in `CONVENTIONS.md` (`brst`, `mkgreen`), we turn the unpredictable nature of an LLM into a repeatable, scriptable engine.
