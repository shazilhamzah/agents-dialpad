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
