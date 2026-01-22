# aico

`aico` is an LLM client designed for the software engineering lifecycle. It treats the Large Language Model as a subordinate implementation engine, empowering you to focus on the **Architect** role.

Unlike agents that try to take over, `aico` is a "hands-on" tool. You explicitly manage the context window to define architectural boundaries, plan changes in natural language, and generate standard unified diffs that you review and apply.

## Philosophy

`aico` is built on three core pillars that prioritize correctness and maintainability over raw speed.

- **It's a tool, not an agent.** `aico` does not execute code or edit files autonomously. It reads input and produces patches. This ensures you remain the gatekeeper of your codebase.

- **Unix philosophy.** `aico` is composable. It outputs clean, machine-readable data to `stdout`, ready to be piped into standard tools like `patch` or `delta`.

- **Architectural control.** By explicitly `add`ing and `drop`ping files from the session, you force the model to focus on the specific problem space, reducing hallucinations and preventing "spaghetti code" suggestions that ignore your project's structure.

## The workflow: specification-driven development

`aico` is unopinionated, but it shines when you use a disciplined, specification-first workflow. This example demonstrates building an "Apply Voucher" feature by defining behavior before implementation.

### 1. Alignment (`ask`)

Don't jump straight to code. First, establish context and align on the design.

```bash
# Define the architectural boundary
aico add app/services/cart.py app/models/voucher.py

# Plan the feature without writing code
aico ask "We need a robust 'Apply Voucher' method. It must validate dates and check usage limits. Discuss the edge cases."
```

### 2. Specification (`gen`)

Generate a failing test case (the specification) to codify the requirements. This ensures the implementation will meet your standards.

```bash
aico gen "Generate a high-level unit test for the happy path and the expired voucher case." > tests/voucher_test.py
```

### 3. Implementation (`gen`)

Now, instruct `aico` to write the minimal code to satisfy the spec.

```bash
# Add the test to context so the model sees the goal
aico add tests/voucher_test.py

# Generate the implementation patch
aico gen "Implement the apply_voucher method to pass the test."
```

### 4. Review and apply (`last`)

Review the generated diff. If it looks correct, apply it.

```bash
# Apply to disk
aico last | patch -p1
```

### Why this works

- **Review-first:** `aico` forces you to review changes before they exist. By generating diffs (`gen`) that must be manually applied (`patch`), you are never surprised by an edit. You remain the gatekeeper of your codebase.
- **Plan vs Execute:** The distinction between `ask` (discussion) and `gen` (code) is intentional. It encourages you to fully resolve the design in natural language during the `ask` phase before committing to syntax in the `gen` phase.
- **Focused context:** Manually `add`ing and `drop`ping files ensures the LLM focuses only on relevant code, keeping token costs low and reasoning sharp.
- **Correcting the brain:** By using `aico edit` to fix mistakes in the history rather than the file, we prevent the model from spiraling into bad patterns.

### Optimization: "Prompt Engineering" via conventions

Once you settle on a workflow, typing verbose prompts becomes tedious. You can teach `aico` your vocabulary by adding a `CONVENTIONS.md` file to your project root. Because `aico` sees this file in its context (once you've `aico add`ed it), it "learns" your shorthand instantly.

Here is the cheat sheet we use to speed up the workflow above:

| Command | Phase | Instruction to AI |
| -- | -- | -- |
| **`brst`** | Planning | **Brainstorm.** Do not write code yet. Read the request, summarize your understanding, and ask numbered questions to clarify ambiguity. |
| **`cnfrm`** | Planning | **Confirm.** "Yes, the plan is correct." Output the final plan. If you still have doubts, ask more questions. |
| **`mkgold`** | Spec | **Make Golden.** Generate a "Golden Path" test case that describes the feature's successful behavior. |
| **`mkgreen`** | Exec | **Make Green.** Write the minimal implementation code required to make the spec pass. |
| **`mkcurl`** | Verify | **Make Curl.** Provide a one-line `curl` command to test this endpoint on localhost. |

The trick is to make your abbreviations distinct from regular words, so the model doesn't confuse them with normal language.

### Optimization: use natural language for architectural specifications

While Unit Tests are familiar, they force you to decide on implementation details very early in the process. This can lead to brittleness if you change your mind during the implementation phase.

For complex features, we recommend [Markdown with Gherkin (MDG)](https://github.com/cucumber/gherkin/blob/main/MARKDOWN_WITH_GHERKIN.md).

MDG is an alternative syntax for Cucumber that allows you to embed executable tests directly in Markdown. Because it relies on natural language, it lets you define the behavior (the "what") without locking yourself into specific implementation choices (the "how") too early. In this workflow, the Markdown file *is* the test.

## Installation

Install `aico` from source using `cargo`:

```bash
cargo install --git https://github.com/jurriaan/aico.git
```

Ensure that `$HOME/.cargo/bin` is in your `PATH`.

## Configuration

`aico` supports OpenAI models directly and non-OpenAI models (e.g., Claude, Gemini) via OpenRouter. Set the appropriate API key as an environment variable.

For example:

-   For OpenAI models:
    ```bash
    export OPENAI_API_KEY="sk-..."
    ```
-   For non-OpenAI models via OpenRouter:
    ```bash
    export OPENROUTER_API_KEY="sk-..."
    ```

You specify which model to use when you initialize a session. Use the `openai/` prefix for OpenAI models and `openrouter/` for others:

```bash
aico init --model "openrouter/google/gemini-3-pro-preview"
```

**Note:** All models must use the explicit provider prefix (`openai/<model>` or `openrouter/<model>`).

## Essential commands

This is a focused list of the core lifecycle commands. Run `aico --help` for the full reference.

- `aico init`: Initialize a new session in the current directory.
- `aico add <files...>`: Add files to the context window.
- `aico ask "<text>"`: Discuss and plan without generating code blocks.
- `aico gen "<text>"`: Generate code changes (output as Unified Diff).
- `aico last`: View the last output (use `| patch -p1` to apply).
- `aico undo`: Exclude the last turn from history.

## Advanced features

- **Branching:** Use `aico session-fork` to experiment with different solutions on parallel history branches without duplicating data.
- **Addons:** Extend `aico` with scripts in `.aico/addons/`. Includes built-in support for commit message generation (`aico commit`) and summarization (`aico summarize`).

## Contributing

This is a tool I use personally; PRs are welcome but feature requests may be declined to keep the tool focused.

### Development

```bash
# Setup your development environment
./script/setup

# Run linting and type checking
./script/lint

# Run tests
./script/test
```
