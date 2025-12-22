# Example Workflow: Specification-Driven Development

`aico` is unopinionated by design, but it shines when you pair it with strong project conventions.

The goal of this workflow isn't just speed—it's **correctness**. It forces us to define the behavior first, and only then generate the implementation. We treat `aico` less like a chatty assistant and more like a junior engineer who strictly follows the architectural instructions in our `CONVENTIONS.md`.

## Setup: "Prompt Engineering" via Conventions

Instead of typing long, repetitive prompts like *"Please look at the architecture and brainstorm ideas..."* for every task, we define shorthand commands in the project's `CONVENTIONS.md`. Because `aico` sees this file in its context, it "learns" our vocabulary instantly.

Here is the cheat sheet we use:

| Command       | Phase    | Instruction to AI                                                                                                                       |
| ------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **`brst`**    | Planning | **Brainstorm.** Do not write code yet. Read the request, summarize your understanding, and ask numbered questions to clarify ambiguity. |
| **`yasss`**   | Planning | **Confirm.** "Yes, the plan is correct." Output the final plan. If you still have doubts, ask more questions.                           |
| **`mkgold`**  | Spec     | **Make Golden.** Generate a "Golden Path" Gherkin scenario (MDG) that describes the feature's successful behavior.                      |
| **`mkgreen`** | Exec     | **Make Green.** Write the minimal implementation code required to make the spec pass.                                                   |
| **`mkcurl`**  | Verify   | **Make Curl.** Provide a one-line `curl` command to test this endpoint on localhost.                                                    |

## Walkthrough: Building an "Apply Voucher" Feature

Let's say we need to add an endpoint to apply a discount voucher. Here is how we move from idea to shipped code.

### Phase 1: Alignment (The "brst" Loop)

Don't jump straight to code generation. First, ensure the AI understands the architectural boundaries.

1. **Establish Context:**
   Give the AI examples of existing patterns in your project.

   ```sh
   aico add app/services/similar_service.py app/controllers/similar_controller.py
   ```

1. **Start Brainstorming:**
   Ask the AI to brainstorm (`brst`). It reads your conventions and knows `brst` means "ask questions first."

   ```sh
   aico ask "We need a new 'Apply Voucher' endpoint. It should validate dates and check usage limits. brst"
   ```

1. **Refine the Plan:**
   The AI will reply with questions like *"Should validation be case-insensitive?"* or *"Where is the usage limit stored?"*.

   Answer these questions in the chat.

   ```sh
   aico ask "1. Yes, case-insensitive. 2. Stored in Redis. brst"
   ```

1. **Lock it in:**
   When the AI's summary matches your vision, confirm it.

   ```sh
   aico ask "yasss"
   ```

### Phase 2: The Specification

Now that we agree on *what* we are building, generate a formal specification. We use [Markdown with Gherkin (MDG)](https://github.com/cucumber/gherkin/blob/main/MARKDOWN_WITH_GHERKIN.md) because LLMs are excellent at both reading and producing it.

1. **Generate the Spec:**

   ```sh
   aico gen "mkgold"
   ```

   *Result:* `aico` generates a new file `features/apply_voucher.feature.md` describing the happy path.

1. **Review and Apply:**

   ```sh
   aico last | patch -p1
   ```

1. **Switch Context:**
   Now that the spec exists, add it to the context. This file is now the **source of truth** for the implementation.

   ```sh
   aico add features/apply_voucher.feature.md
   ```

### Phase 3: The Red-Green Loop

We have a failing test (the spec) and a plan. It's time to implement.

1. **Generate the Code:**
   Use the `mkgreen` shorthand. This tells `aico`: *"Read the Gherkin spec, look at `similar_service.py` for style, and write the implementation."*

   ```sh
   aico gen "mkgreen"
   ```

1. **Fix the History, Not the File:**
   Before applying the code, check the diff (`aico last`). If the model hallucinated a variable name or violated a convention, **do not fix it in your editor yet.** Fix it in the chat history using `aico edit`.

   *Why?* If you fix it silently in the code, the model still "remembers" generating the wrong name and might make the same mistake in the next turn. By editing the history, you correct the model's memory, ensuring it learns for the rest of the session.

1. **Apply the Code:**

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

1. **Summarize and Reset:**
   LLM sessions get noisy over time as context grows. Once the feature is merged, use the `summarize` addon to archive the discussion and clear the token window for the next task.

   ```sh
   aico summarize
   ```

## Why this works

- **Focused Context:** Manually `add`ing and `drop`ping files ensures the LLM focuses only on relevant code, keeping token costs low and reasoning sharp.

- **Correcting the Brain:** By using `aico edit` to fix mistakes in the history rather than the file, we prevent the model from spiraling into bad patterns.

- **Predictability:** Relying on defined abbreviations (`brst`, `mkgreen`) turns the unpredictable nature of an LLM into a repeatable engine.
