# Guide: Advanced history management

As a session grows, you may want to manage token usage by controlling the "active window" of history. While `undo` excludes specific pairs, `set-history` allows you to slide the start of the window forward, effectively "forgetting" older turns without deleting them from the logs.

## 1. Setup

Initialize a session and generate some history.

```console
$ aico init --model "openai/test-model"
Initialized session file: .ai_session.json
$ aico ask "Turn 1"
Response 1
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.02
$ aico ask "Turn 2"
Response 2
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.04
$ aico ask "Turn 3"
Response 3
Tokens: 10 sent, 5 received. Cost: $0.02, current chat: $0.06
$
```

## 2. Sliding the window

We have 3 pairs (IDs 0, 1, 2). Let's say we want to focus only on the most recent turn. We set the history start index to `2`.

```console
$ aico set-history 2
History context will now start at pair 2.
$
```

Verify the log. Notice that IDs 0 and 1 are no longer visible in the **Active Context Log**. They still exist on disk, but they will not be sent to the LLM in the next request.

```console
$ aico log
        Active Context Log        
 ID  Role       Message Snippet    
  2  user       Turn 3             
     assistant  Response 3         
$
```

## 3. Accessing "hidden" history

Even though the history window has moved, you can still access older messages using `aico last` if you know the index.

```console
$ aico last 0
Response 1
$
```

## 4. Resetting the window

You can restore the full history by setting the index back to 0.

```console
$ aico set-history 0
History context reset. Full chat history is now active.
$ aico log
        Active Context Log        
 ID  Role       Message Snippet    
  0  user       Turn 1             
     assistant  Response 1         
  1  user       Turn 2             
     assistant  Response 2         
  2  user       Turn 3             
     assistant  Response 3         
$
```

## 5. Clearing context completely

If you want to start a fresh topic without creating a new session branch, you can clear the history window entirely.

```console
$ aico set-history clear
History context cleared.
$ aico log
No message pairs found in active history.
$
```
