# Addon: Refine

The `refine` addon allows you to rewrite a specific conversational turn without resetting the entire session. It works by forking the session, rewinding to the target point, generating a new response based on your critique, and surgically splicing it back into the main history.

> **Note**: This addon requires `jq` to be installed on your system.

## 1. Setup

Initialize the session and context.

```console
$ aico init --model "openai/test-model"
Initialized session file: .ai_session.json
$
```

## 2. Create the "Mistake"

First, we generate a response that we intend to refine later. We'll use a specific prompt that the Mock LLM recognizes.

```console
$ aico ask "Explain this code"
This code is a Python script.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.02
$
```

Verify the log shows this interaction.

```console
$ aico log
              Active Context Log              
 ID  Role       Message Snippet               
  0  user       Explain this code             
     assistant  This code is a Python script. 
$
```

## 3. Refine the Response

Now, we use `aico refine` to change the output. We instruct the AI to be more specific.

```console
$ aico refine "Refine this to say it is a Rust script"
Refining response at index 0 (Mode: conversation)...
This is a Rust script.
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.04
Refinement complete (Original pair hidden, new pair spliced).
$
```

## 4. Verification

Check the log. The original pair (ID 0) should now be excluded `[-]`, and a new pair (ID 1) should be active containing the corrected response.

```console
$ aico log
               Active Context Log               
   ID  Role       Message Snippet               
 0[-]  user       Explain this code             
       assistant  This code is a Python script. 
    1  user       Explain this code             
       assistant  This is a Rust script.        
$
```

Check the content of the last message to ensure it matches the refinement.

```console
$ aico last
This is a Rust script.
$
```
