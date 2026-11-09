# C1 Findings: Claude Code Permission Control Protocol (Part 0 Spike)

Recorded from live runs of Claude Code (v2.1.318) on branch `spike/c1-claude-control`.

---

## 1. Key Finding: CLI Invocation

Claude Code requires `--permission-prompt-tool stdio` alongside `--permission-prompts host`. Without `--permission-prompt-tool stdio`, Claude Code print-mode (`-p`) assumes there is no interactive host attached to stdio and auto-denies any tool requiring approval with an unhandled exception or static denial.

### Working CLI Command
```bash
claude -p \
  --input-format stream-json \
  --output-format stream-json \
  --verbose \
  --permission-mode default \
  --permission-prompts host \
  --permission-prompt-tool stdio
```

---

## 2. Protocol Message Frames

### (a) Initial User Prompt (stdin)
Passed on standard input as a single line JSON frame:
```json
{"type": "user", "message": {"role": "user", "content": "Run a powershell command to write text to foo.txt"}}
```

### (b) Permission Request Frame (`control_request` from stdout)
Emitted by Claude Code when a tool needs user approval:
```json
{
  "type": "control_request",
  "request_id": "0cdf1176-3c6e-4e80-8514-742df16635c5",
  "request": {
    "subtype": "can_use_tool",
    "tool_name": "PowerShell",
    "display_name": "PowerShell",
    "input": {
      "command": "if (Test-Path foo.txt) { \"foo.txt already exists with content:\"; Get-Content foo.txt } else { \"Hello from PowerShell!\" | Out-File -FilePath foo.txt -Encoding utf8; Get-Content foo.txt }",
      "description": "Write text to foo.txt if it doesn't already exist"
    },
    "description": "Write text to foo.txt if it doesn't already exist",
    "decision_reason_type": "subcommandResults",
    "tool_use_id": "toolu_01FtEfmXa2EkrpVMJZzWjGBx"
  }
}
```

Key attributes:
- `request_id`: Unique UUID to match in response.
- `request.subtype`: `"can_use_tool"`.
- `request.tool_name`: Name of tool (`"PowerShell"`, `"Bash"`, `"Write"`, `"Edit"`, etc.).
- `request.input`: Tool arguments dict.
- `request.tool_use_id`: The underlying model tool use call id.

### (c) Allow Response Frame (stdin)
Written to standard input to approve the action:
```json
{
  "type": "control_response",
  "response": {
    "subtype": "success",
    "request_id": "0cdf1176-3c6e-4e80-8514-742df16635c5",
    "response": {
      "behavior": "allow",
      "updatedInput": {
        "command": "if (Test-Path foo.txt) { \"foo.txt already exists with content:\"; Get-Content foo.txt } else { \"Hello from PowerShell!\" | Out-File -FilePath foo.txt -Encoding utf8; Get-Content foo.txt }",
        "description": "Write text to foo.txt if it doesn't already exist"
      }
    }
  }
}
```
Claude immediately proceeds, executes the tool, and outputs a `tool_result` event with `"permission_decision": {"decision": "accept", "source": "user_temporary"}`.

### (d) Deny Response Frame (stdin)
Written to standard input to block the action:
```json
{
  "type": "control_response",
  "response": {
    "subtype": "success",
    "request_id": "f0b6c88b-5454-4a73-b3af-7532af00c5de",
    "response": {
      "behavior": "deny",
      "message": "The user denied this"
    }
  }
}
```
Claude halts execution of that tool, returns a `tool_result` event with `"is_error": true`, `"content": "The user denied this"`, and `"permission_decision": {"decision": "reject", "source": "user_reject"}`. The agent turn continues, adapting to the user's rejection.

### (e) Final Result Frame (`result` from stdout)

#### On Allowed Execution:
```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "result": "I ran a PowerShell command that created `foo.txt` in the working directory and wrote this line to it:\n\n```\nHello from PowerShell!\n```\n\nThe command was set to leave `foo.txt` alone if it already existed. It didn't exist, so this is a new file.",
  "duration_ms": 8135,
  "total_cost_usd": 0.1426114,
  "permission_denials": [],
  "session_id": "e7bee746-3727-4f4f-a2be-4d267676f318"
}
```

#### On Denied Execution:
```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "result": "I didn't write foo.txt because you declined the PowerShell command. It would have written \"Hello from PowerShell\" to foo.txt in the working directory, and only if the file didn't already exist.\n\nTo go ahead, tell me what text you want in the file, and whether to overwrite foo.txt or add to the end if it's already there. You can also run it yourself:\n\n```powershell\n\"your text here\" | Out-File -FilePath foo.txt -Encoding utf8\n```",
  "duration_ms": 6965,
  "total_cost_usd": 0.1419278,
  "permission_denials": [
    {
      "tool_name": "PowerShell",
      "tool_use_id": "toolu_01LRbsSnKaubravXwPGmxDs4",
      "tool_input": {
        "command": "if (Test-Path foo.txt) { \"foo.txt already exists:\"; Get-Content foo.txt } else { \"Hello from PowerShell\" | Out-File -FilePath foo.txt -Encoding utf8; Get-Content foo.txt }",
        "description": "Write text to foo.txt if it doesn't already exist"
      }
    }
  ],
  "session_id": "58e562f1-07eb-41ac-a908-85c2863274be"
}
```

---

## 3. Process Lifecycle & Teardown

- **Does it exit on its own after `result`?**
  No. Because `--input-format stream-json` keeps stdin open for potential multi-turn input, Claude Code remains active after outputting the `result` event.
- **Teardown mechanism:**
  Closing standard input (`proc.stdin.close()` / EOF) signals completion. Upon receiving EOF on stdin, the Claude Code subprocess exits cleanly with exit code 0.

---

## 4. Session Resumption (`--resume <id>`)

`--resume <session_id>` works smoothly alongside `--input-format stream-json --output-format stream-json --permission-prompts host --permission-prompt-tool stdio`.
- When resumed in the same directory (`cwd`), Claude preserves the conversation history, recalls files inspected or created in previous turns, and continues seamlessly.
- Captured and verified in fixture `tests/fixtures/claude_control/resume_run.jsonl`.

---

## 5. Test Fixtures

Recorded anonymized fixture runs are stored in:
- `tests/fixtures/claude_control/allow_run.jsonl`: Full turn with permission request, allow control response, tool execution, and success result.
- `tests/fixtures/claude_control/deny_run.jsonl`: Full turn with permission request, deny control response, rejection tool result, and denial result.
- `tests/fixtures/claude_control/resume_run.jsonl`: Follow-up turn resuming session via `--resume <session_id>`.

---

## 6. Verification Checklist for Part 1

1. Add `"ask": "default"` mode mapping for Claude Code provider.
2. If `chat["mode"] == "ask"`:
   - Add flags: `["--input-format", "stream-json", "--permission-prompts", "host", "--permission-prompt-tool", "stdio"]`.
   - Keep `proc.stdin` open throughout the turn.
   - Parse `control_request` lines with `subtype == "can_use_tool"`.
   - Yield `approval` event: `{"type": "approval", "id": req_id, "tool": tool_name, "input": input}`.
   - Wait on `Run.wait_decision(req_id, timeout)`.
   - Write formatted `control_response` (allow with `updatedInput` or deny with `message`).
   - Yield `approval_result` event: `{"type": "approval_result", "id": req_id, "allow": allow, "by": by}`.
   - Close stdin when `result` event is encountered.

---

# Part 2 Spike: Antigravity ACP (Agent Client Protocol) Findings

Recorded from live runs of `agy acp` (Antigravity ACP Server v1.5.3) on branch `spike/c1-agy-acp` via `tools/spikes/agy_acp.py`.

---

## 7. Protocol Overview & Invocation

Antigravity natively implements the **Agent Client Protocol (ACP)** specification over stdio using newline-delimited JSON-RPC 2.0.

### Starting the Server
```bash
agy acp
```
Key observations:
- Speaks newline-delimited JSON-RPC 2.0 on `stdin`/`stdout`.
- Stderr outputs diagnostic logs without interfering with stdio JSON-RPC.
- Supports `--dangerously-skip-permissions` if auto-approval is desired; default behavior surfaces `session/request_permission` requests for sensitive tool actions like `run_command`.

---

## 8. Protocol Message Flow & Real Frame Examples

### Step 1: `initialize` (Client → Server)
Negotiates capabilities and client identity.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": 1,
    "capabilities": {},
    "clientInfo": {
      "name": "dialtone-acp-spike",
      "version": "0.1.0"
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": 1,
    "agentCapabilities": {
      "loadSession": true,
      "load_session": true,
      "promptCapabilities": {
        "image": true,
        "audio": false,
        "embeddedContext": true
      },
      "sessionCapabilities": {
        "resume": {},
        "close": {},
        "load": {},
        "list": {},
        "additionalDirectories": {}
      },
      "session_capabilities": {
        "resume": {},
        "close": {},
        "load": {},
        "list": {},
        "additionalDirectories": {}
      },
      "auth": {
        "logout": {}
      },
      "_meta": {
        "antigravity": {
          "tier": true,
          "systemPrompt": {
            "append": true
          }
        }
      }
    },
    "agentInfo": {
      "name": "Antigravity ACP Server",
      "version": "1.5.3"
    },
    "authMethods": [
      {"id": "oauth-personal", "name": "Log in with Google"},
      {"id": "oauth-business", "name": "Log in with Gemini Enterprise"},
      {"id": "gemini-api-key", "name": "Gemini API key"},
      {"id": "agent-platform", "name": "Gemini Enterprise Agent Platform"}
    ]
  }
}
```
**Key finding:** `loadSession: true` is explicitly declared in `agentCapabilities`.

---

### Step 2: Creating a Session (`session/new`) or Resuming (`session/load`)

#### Starting a New Session:
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/new",
  "params": {
    "cwd": "C:/path/to/workspace",
    "mcpServers": []
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "sessionId": "bd191a62-b288-4fe1-aa68-a4d93b1344a0",
    "models": {
      "availableModels": [
        {"modelId": "gemini-4-argon-medium", "name": "Gemini 4 Argon (Medium)"},
        {"modelId": "gemini-3.8-flash-medium", "name": "Gemini 3.8 Flash (Medium)"},
        {"modelId": "claude-sonnet-5-5-medium", "name": "Claude Sonnet 5.5 (Medium)"}
      ],
      "currentModelId": "gemini-4-argon-medium"
    },
    "modes": {
      "currentModeId": "default",
      "availableModes": [
        {"id": "default", "name": "Default", "description": "Ask before edits and commands, per your permission settings."},
        {"id": "accept-edits", "name": "Accept edits", "description": "Approve file edits in the workspace without asking."},
        {"id": "plan", "name": "Plan", "description": "Plan carefully before executing a task."}
      ]
    },
    "configOptions": [
      {
        "id": "model",
        "name": "Model",
        "category": "model",
        "type": "select",
        "currentValue": "gemini-4-argon",
        "options": [{"value": "gemini-4-argon", "name": "Gemini 4 Argon"}, ...]
      },
      {
        "id": "thought_level",
        "name": "Thinking Level",
        "category": "thought_level",
        "type": "select",
        "currentValue": "medium",
        "options": [{"value": "low", "name": "Low"}, {"value": "medium", "name": "Medium"}, {"value": "high", "name": "High"}]
      },
      {
        "id": "mode",
        "name": "Mode",
        "category": "mode",
        "type": "select",
        "currentValue": "default",
        "options": [...]
      }
    ]
  }
}
```

#### Resuming an Existing Session (`session/load`):
`session/load` is fully supported!
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/load",
  "params": {
    "sessionId": "bd191a62-b288-4fe1-aa68-a4d93b1344a0",
    "cwd": "C:/path/to/workspace",
    "mcpServers": []
  }
}
```
**Behavior:**
1. Server immediately streams previous turns via `session/update` notifications (`user_message_chunk`, `tool_call`, `agent_message_chunk`).
2. Server responds with the result containing `sessionId`, active `models`, `modes`, and `configOptions`.
3. Subsequent `session/prompt` calls continue the conversation context seamlessly.

---

### Step 3: Selecting a Model or Mode (`session/set_config_option`)

The client can change settings dynamically:
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "session/set_config_option",
  "params": {
    "sessionId": "bd191a62-b288-4fe1-aa68-a4d93b1344a0",
    "configId": "model",
    "value": "gemini-3.8-flash"
  }
}
```
**Response:**
Returns the updated `configOptions` array with `currentValue` reflected.

---

### Step 4: Submitting a Prompt (`session/prompt`)

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "session/prompt",
  "params": {
    "sessionId": "bd191a62-b288-4fe1-aa68-a4d93b1344a0",
    "prompt": [
      {
        "type": "text",
        "text": "Run the shell command: echo hello"
      }
    ]
  }
}
```

---

### Step 5: Streaming Updates (`session/update`)

As the agent runs, it emits notifications:
- **`user_message_chunk`**: Echos the user prompt back.
- **`session_info_update`**: Suggests conversation title.
- **`tool_call`**: Initial tool call notification (`status: "in_progress"` or `"pending"`):
  ```json
  {
    "jsonrpc": "2.0",
    "method": "session/update",
    "params": {
      "sessionId": "bd191a62-b288-4fe1-aa68-a4d93b1344a0",
      "update": {
        "sessionUpdate": "tool_call",
        "toolCallId": "call_11802004393518526885",
        "name": "run_command",
        "args": {
          "CommandLine": "echo hello",
          "WaitMsBeforeAsync": 5000,
          "toolSummary": "Run echo hello"
        },
        "status": "in_progress",
        "kind": "execute",
        "title": "echo hello",
        "rawInput": {
          "CommandLine": "echo hello",
          "WaitMsBeforeAsync": 5000,
          "toolSummary": "Run echo hello"
        }
      }
    }
  }
  ```
- **`tool_call_update`**: Emitted when status changes to `"pending"`, `"in_progress"`, or `"completed"`:
  ```json
  {
    "sessionUpdate": "tool_call_update",
    "toolCallId": "call_11802004393518526885",
    "status": "completed",
    "rawOutput": {"output": "Command exited with code 0.\n\nCommand output:\nhello\r\n", "exit_code": 0},
    "content": [{"type": "content", "content": {"type": "text", "text": "Command exited with code 0.\n\nCommand output:\nhello\r\n"}}]
  }
  ```
- **`agent_message_chunk`**: Assistant text deltas:
  ```json
  {
    "sessionUpdate": "agent_message_chunk",
    "content": {"type": "text", "text": "Ran `echo hello`.\n\n**Output:**\n```text\nhello\n```"}
  }
  ```

---

### Step 6: Permission Request & Decision Handling

When a tool requires approval, the server initiates a JSON-RPC request to the client:

**`session/request_permission` Request (Server → Client):**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "session/request_permission",
  "params": {
    "sessionId": "bd191a62-b288-4fe1-aa68-a4d93b1344a0",
    "toolCall": {
      "sessionUpdate": "tool_call",
      "toolCallId": "call_11802004393518526885",
      "name": "run_command",
      "args": {
        "CommandLine": "echo hello",
        "WaitMsBeforeAsync": 5000,
        "toolSummary": "Run echo hello"
      },
      "status": "pending",
      "kind": "execute",
      "title": "echo hello",
      "rawInput": {
        "CommandLine": "echo hello",
        "WaitMsBeforeAsync": 5000,
        "toolSummary": "Run echo hello"
      }
    },
    "options": [
      {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
      {"optionId": "deny", "name": "Deny", "kind": "reject_once"}
    ]
  }
}
```

#### Client Allow Response:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "outcome": {
      "outcome": "selected",
      "optionId": "allow"
    }
  }
}
```
*Behavior:* Tool status transitions to `in_progress` and then `completed` with stdout/stderr recorded in `rawOutput`.

#### Client Deny Response:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "outcome": {
      "outcome": "selected",
      "optionId": "deny"
    }
  }
}
```
*Behavior:* Tool status immediately transitions to `failed` (`rawOutput: {"output": ""}`), and the prompt completes without executing the command.

---

### Step 7: Final Prompt Response & Process Shutdown

#### Prompt Completion (`session/prompt` response from Server):
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "stopReason": "end_turn",
    "usage": {
      "inputTokens": 9892,
      "outputTokens": 88,
      "cachedReadTokens": 5633,
      "cachedWriteTokens": 0,
      "thoughtTokens": 25,
      "totalTokens": 15613
    }
  }
}
```

#### Process Teardown:
- The `agy acp` server stays alive awaiting the next JSON-RPC command.
- Closing standard input (`proc.stdin.close()`) signals EOF. The server immediately and cleanly terminates with exit code `0`.

---

## 9. Recorded Fixtures

Recorded anonymized fixture runs are stored in:
- `tests/fixtures/agy_acp/allow_run.jsonl`: Full turn with permission request, allow decision, tool execution, output capture, and end of turn.
- `tests/fixtures/agy_acp/deny_run.jsonl`: Full turn with permission request, deny decision, tool marked failed, and end of turn.
- `tests/fixtures/agy_acp/resume_run.jsonl`: Full session resume via `session/load`, history replay, and second prompt turn.

---

## 10. Implementation Plan for Part 3 (Antigravity ACP Approvals)

1. **Provider Architecture:**
   - In `AntigravityProvider`: when `chat["mode"] == "ask"`, run via `agy acp` instead of `-p` CLI.
   - For `readonly`, `edit`, and `full` modes: keep existing `-p` CLI provider untouched.
2. **Session Resumption:**
   - Because `session/load` is fully supported, each turn can either launch `agy acp` and call `session/load`, or keep an active worker process alive between turns.
3. **Event Normalization:**
   - `session/update` (`agent_message_chunk`) → `{"type": "text", "text": chunk}`.
   - `session/update` (`tool_call` with `name == "run_command"`) → `{"type": "tool_use", ...}`.
   - `session/request_permission` → `{"type": "approval", "id": req_id, "tool": tool_name, "command": command, "description": desc}`.
   - Wait on `run.wait_decision(req_id, timeout)`.
   - Send JSON-RPC response with `optionId: "allow" | "deny"`.
   - Yield `approval_result` event: `{"type": "approval_result", "id": req_id, "allow": allow, "by": by}`.
   - `session/update` (`tool_call_update` status completed/failed) → `{"type": "tool_result", ...}`.
   - `session/prompt` response (`stopReason: "end_turn"`) → `{"type": "done", "is_error": False}`.
4. **Testing:**
   - Add `tests/fake_agents/fake_agy_acp.py` replaying the recorded ACP messages.
   - Add integration tests for Antigravity in `ask` mode matching Claude's test suite.
