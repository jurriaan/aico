# Feature: Basic Workflow

## 1. Initialization
First, initialize an aico session to define the model and project root.

```console
$ aico init --model "openai/test-model" #=> --regex Initialized session file: .*\.ai_session\.json
```

## 2. Planning and Discussion
Use `ask` for high-level discussion or to explain existing code.

```console
$ aico ask "Explain this code"
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.02
This code is a Python script.
$
```

## 3. Context Management
Add relevant files to the context. This sets the "Ground Truth" for the AI.

```console
$ echo "hello world" > hello.txt
$ aico add hello.txt
Added file to context: hello.txt
$
```

## 4. Execution and Patching
Use `gen` to produce structural changes. The resulting diff can be piped to `patch`.

```console
$ aico gen "add a comment"
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.04
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1,2 @@
+# a comment
 hello world
$ aico last | patch -p1
patching file hello.txt
$ cat hello.txt
# a comment
hello world
$
```

## 5. Manual Corrections
Sometimes the AI nearly gets it right. You can fix the history using `aico edit` so the AI "learns" from the correction.

```console
$ echo "def do(a, b):" > math_utils.py
$ echo "    return a + b" >> math_utils.py
$ aico add math_utils.py
Added file to context: math_utils.py
$ aico gen "Rename 'do' to 'add_numbers' and use type hints" #=> --regex .*def add_nums.*
$ env EDITOR="sed -i s/add_nums/add_numbers/" aico edit
Updated response for message pair 2.
$ aico last | patch -p1
patching file math_utils.py
$ grep "def add_numbers" math_utils.py
def add_numbers(a: int, b: int) -> int:
$
```

## 6. Transparency and Status
Verify context files and token usage with the `status` command.

```console
$ aico log
                       Active Context Log                       
 ID  Role       Message Snippet                                 
  0  user       Explain this code                               
     assistant  This code is a Python script.                   
  1  user       add a comment                                   
     assistant  File: hello.txt                                 
  2  user       Rename 'do' to 'add_numbers' and use type hints 
     assistant  File: math_utils.py                             
$ aico drop hello.txt
Dropped file from context: hello.txt
$ aico status
╭─────────────────────────────── Session 'main' ───────────────────────────────╮
│                              openai/test-model                               │
╰──────────────────────────────────────────────────────────────────────────────╯

   Tokens        Cost Component                                                 
(approx.)                                                                       
───────── ─────────── ──────────────────────────────────────────────────────────
      407    $0.40700 system prompt                                             
      405    $0.40500 alignment prompts (worst-case)                            
       86    $0.08600 chat history                                              
                        └─ Active window: 3 pairs (IDs 0-2), 3 sent.            
                           (Use `aico log`, `undo`, and `set-history` to manage)
───────── ─────────── ─────────────────── Context Files (1) ────────────────────
       23    $0.02300 math_utils.py                                             
───────── ─────────── ──────────────────────────────────────────────────────────
     ~921    $0.92100 Total                                                     

╭─────────────────────────────── Context Window ───────────────────────────────╮
│                      (921 of 1,000 used - 8% remaining)                      │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸       │
╰──────────────────────────────────────────────────────────────────────────────╯
$
```

## 7. History Management (Undo/Redo)
`aico` uses a "soft-delete" approach to history. You can exclude messages from the next prompt without losing them from the log.

```console
$ aico undo
Marked pair at index 2 as excluded.
$ aico log
                        Active Context Log                        
   ID  Role       Message Snippet                                 
    0  user       Explain this code                               
       assistant  This code is a Python script.                   
    1  user       add a comment                                   
       assistant  File: hello.txt                                 
 2[-]  user       Rename 'do' to 'add_numbers' and use type hints 
       assistant  File: math_utils.py                             
$ aico redo
Re-included pair at index 2 in context.
$
```

## 8. Archiving and Resetting (Summarize)
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
            405           $0.40500 alignment prompts (worst-case)               
                           $0.0000 chat history                                 
─────────────── ────────────────── ───────────── Context Files (2) ─────────────
             50           $0.05000 PROJECT_SUMMARY.md                           
             23           $0.02300 math_utils.py                                
─────────────── ────────────────── ─────────────────────────────────────────────
           ~885           $0.88500 Total                                        

╭─────────────────────────────── Context Window ───────────────────────────────╮
│                     (885 of 1,000 used - 12% remaining)                      │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━          │
╰──────────────────────────────────────────────────────────────────────────────╯
$ cat PROJECT_SUMMARY.md
### Recent Developments
- Refactored `math_utils.py` to use type hints.
### Comprehensive Project Summary
A collection of utilities including math functions.
$
```
```
