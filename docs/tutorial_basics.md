# Getting Started

This tutorial walks you through the core workflow of `aico`: planning, implementing, and refining code with an LLM.

## 1. Initialization

Start by initializing a session in your project root. We specify the model we want to use.

```console
$ aico init --model "openai/test-model"
Initialized session file: .ai_session.json
$
```

## 2. Context & Understanding

Start by defining the context boundary. We add a file and verify the model understands it.

```console
$ echo "def add(a, b): return a + b" > math.py
$ aico add math.py
Added file to context: math.py
$ aico ask "Explain this code"
This code is a Python script.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.02
$
```

## 3. Directed Execution (Generating Diff)

Now, we direct the model to modify the source. We use `gen` to produce a standard Unified Diff.

```console
$ aico gen "Rename 'add' to 'sum_values' and add type hints"
--- a/math.py
+++ b/math.py
@@ -1 +1,2 @@
-def add(a, b): return a + b
+def sum_values(a: int, b: int) -> int:
+    return a + b
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.04
$
```

## 4. Manual Corrections (The Learning Loop)

Sometimes the model makes a small mistake, or you simply change your mind. Instead of just fixing the file, you should fix the **history**. This ensures the model "remembers" your correction for future turns.

We use `aico edit` to modify the last LLM response.

*(Note: In this example, we use `sed` to simulate an editor. In reality, `aico edit` opens your default `$EDITOR`.)*

```console
$ env EDITOR="sed -i s/sum_values/calc_sum/" aico edit
Updated response for message pair 1.
$
```

Now we apply the corrected patch.

```console
$ aico last | patch -p1
patching file math.py
$ grep "def calc_sum" math.py
def calc_sum(a: int, b: int) -> int:
$
```

## 5. Transparency and Status
Verify context files and token usage with the `status` command.

```console
$ aico log
                       Active Context Log                       
 ID  Role       Message Snippet                                 
  0  user       Explain this code                               
     assistant  This code is a Python script.                   
  1  user       Rename 'add' to 'sum_values' and add type hints 
     assistant  File: math.py                                   
$ aico drop math.py
Dropped file from context: math.py
$ aico status
╭─────────────────────────────── Session 'main' ───────────────────────────────╮
│                              openai/test-model                               │
╰──────────────────────────────────────────────────────────────────────────────╯

   Tokens        Cost Component                                                 
(approx.)                                                                       
───────── ─────────── ──────────────────────────────────────────────────────────
      407    $0.40700 system prompt                                             
      393    $0.39300 alignment prompts (worst-case)                            
       57    $0.05700 chat history                                              
                        └─ Active window: 2 pairs (IDs 0-1), 2 sent.            
                           (Use `aico log`, `undo`, and `set-history` to manage)
───────── ─────────── ──────────────────────────────────────────────────────────
     ~857    $0.85700 Total                                                     

╭─────────────────────────────── Context Window ───────────────────────────────╮
│                     (857 of 1,000 used - 14% remaining)                      │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━            │
╰──────────────────────────────────────────────────────────────────────────────╯
$
```

## 6. History Management (Undo/Redo)
`aico` uses a "soft-delete" approach to history. You can exclude messages from the next prompt without losing them from the log.

```console
$ aico undo
Marked pair at index 1 as excluded.
$ aico log
                        Active Context Log                        
   ID  Role       Message Snippet                                 
    0  user       Explain this code                               
       assistant  This code is a Python script.                   
 1[-]  user       Rename 'add' to 'sum_values' and add type hints 
       assistant  File: math.py                                   
$ aico redo
Re-included pair at index 1 in context.
$
```

## 7. Archiving and Resetting (Summarize)
The `summarize` addon archives the history and resets the active window.

```console
$ aico summarize #=> --regex .*Archived summary.*
$ aico status
╭─────────────────────────────── Session 'main' ───────────────────────────────╮
│                              openai/test-model                               │
╰──────────────────────────────────────────────────────────────────────────────╯

         Tokens               Cost Component                                    
      (approx.)                                                                 
─────────────── ────────────────── ─────────────────────────────────────────────
            407           $0.40700 system prompt                                
            393           $0.39300 alignment prompts (worst-case)               
                           $0.0000 chat history                                 
─────────────── ────────────────── ───────────── Context Files (1) ─────────────
             48           $0.04800 PROJECT_SUMMARY.md                           
─────────────── ────────────────── ─────────────────────────────────────────────
           ~848           $0.84800 Total                                        

╭─────────────────────────────── Context Window ───────────────────────────────╮
│                     (848 of 1,000 used - 15% remaining)                      │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━             │
╰──────────────────────────────────────────────────────────────────────────────╯
$ cat PROJECT_SUMMARY.md
### Recent Developments
- Refactored `math.py` to use type hints.
### Comprehensive Project Summary
A collection of utilities including math functions.
$
```
```
