# C2 Findings: Codex CLI Execution & Protocol (Part 0 Spike)

Recorded from live runs of `codex-cli 0.164.0` (windows-x86_64) on branch `spike/c2-codex`.

---

## 1. CLI Invocation

### Executable Resolution
`codex` executable on PATH (or overridden via `AG_CODEX` environment variable; extra CLI flags via `AG_CODEX_ARGS`).

### First Turn Invocation
```bash
codex exec \
  --json \
  --skip-git-repo-check \
  -C <cwd> \
  -s <sandbox_mode> \
  [-m <model>] \
  -
```

### Resume Turn Invocation
```bash
codex exec \
  --json \
  --skip-git-repo-check \
  [-m <model>] \
  resume \
  <thread_id> \
  -
```

> [!NOTE]
> Flags such as `--json`, `--skip-git-repo-check`, and `-m <model>` can precede `resume`. `codex exec resume` natively takes `[SESSION_ID]` and `[PROMPT]`. Passing `-` instructs Codex to read the prompt from standard input (`stdin`).

---

## 2. Stdin Prompt Support & Windows Command Line Limits

Passing `-` as the `[PROMPT]` argument allows passing the full prompt via standard input (`stdin`).
- Command-line length in Windows is limited to ~32,767 characters. Stdin avoids this limit.
- If stdin is closed immediately after writing the prompt (or EOF delivered), Codex proceeds without hanging.
- Note: If stdin is left open without sending EOF or `-` is omitted while stdin is attached, Codex outputs `Reading additional input from stdin...` to `stderr`. Always pass `-` and close `stdin` after writing the prompt.

---

## 3. Sandbox & Permission Modes

Codex CLI provides built-in sandbox flags:
| agents-dialpad mode | Codex CLI flags | Description |
|---|---|---|
| `readonly` | `-s read-only` | Read-only filesystem access; model cannot execute mutating commands. |
| `edit` | `-s workspace-write` | Workspace writable; command executions permitted within project boundaries. |
| `full` | `--dangerously-bypass-approvals-and-sandbox` | Unrestricted execution. Only available when `allow_full_access` is enabled in config. |

---

## 4. Protocol Message Frames (JSONL)

All events emitted to `stdout` under `--json` are newline-delimited JSON objects.

### (a) Session Start (`thread.started`)
Emitted as the first line of an execution turn.
```json
{"type":"thread.started","thread_id":"01a1bd73-e7fa-7902-b168-08dc2651131d"}
```
- **Session Identifier**: The session ID is stored in the `"thread_id"` field (a UUIDv7 string).
- This `thread_id` must be captured and saved on `chat.session_id` to allow resuming in subsequent turns.

### (b) Turn Started (`turn.started`)
Emitted when model turn processing begins.
```json
{"type":"turn.started"}
```

### (c) Informational / Non-fatal Errors
Internal warnings, hook messages, or metadata warnings may be delivered as completed items without failing the turn.
```json
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"clamping SessionEnd hook timeout to 3s in C:\\Users\\developer\\.codex\\hooks.json"}}
```

### (d) Assistant Text Output (`agent_message`)
Delivered as an item with `type: "agent_message"`.
```json
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"I’ll run that command and report its output."}}
```
- For the final message:
```json
{"type":"item.completed","item":{"id":"item_3","type":"agent_message","text":"`hello`"}}
```

### (e) Command / Tool Execution Start (`item.started` with `command_execution`)
Emitted when Codex initiates a shell command.
```json
{"type":"item.started","item":{"id":"item_2","type":"command_execution","command":"\"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" -Command 'echo hello'","aggregated_output":"","exit_code":null,"status":"in_progress"}}
```
- Corresponds to `tool_use {id, name: "command_execution", input: {command: "..."}}`.

### (f) Command / Tool Execution Result (`item.completed` with `command_execution`)
Emitted when command execution completes.
```json
{"type":"item.completed","item":{"id":"item_2","type":"command_execution","command":"\"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" -Command 'echo hello'","aggregated_output":"hello\r\n","exit_code":0,"status":"completed"}}
```
- `aggregated_output`: Captured command output.
- `exit_code`: Numeric exit code (e.g. 0 for success, non-zero for failure).
- `status`: `"completed"` or `"failed"`.
- Corresponds to `tool_result {id, text: aggregated_output, is_error: exit_code != 0}`.

### (g) Turn Completion & Usage (`turn.completed`)
Emitted at the end of a successful turn.
```json
{"type":"turn.completed","usage":{"input_tokens":36603,"cached_input_tokens":28160,"cache_write_input_tokens":0,"output_tokens":103,"reasoning_output_tokens":10}}
```
- `usage` contains exact token metrics:
  - `input_tokens`
  - `cached_input_tokens`
  - `output_tokens`
  - `reasoning_output_tokens`
- Corresponds to normalised `usage {info: ...}` followed by `done {is_error: false}`.

### (h) Turn Failure / Error (`error` / `turn.failed`)
Emitted if a turn cannot be completed (e.g. invalid model, authentication or provider failure).
```json
{"type":"error","message":"{\"type\":\"error\",\"status\":400,\"error\":{\"type\":\"invalid_request_error\",\"message\":\"The 'invalid-model-xyz' model is not supported when using Codex with a ChatGPT account.\",\"code\":\"model_not_found\"}}"}
{"type":"turn.failed","error":{"message":"{\"type\":\"error\",\"status\":400,\"error\":{\"type\":\"invalid_request_error\",\"message\":\"The 'invalid-model-xyz' model is not supported when using Codex with a ChatGPT account.\",\"code\":\"model_not_found\"}}"}}
```
- Corresponds to normalised `error {message: ...}` followed by `done {is_error: true}`.

---

## 5. Event Normalisation Mapping

| Codex Event | Normalized Event | Notes |
|---|---|---|
| `thread.started` | `session {session_id: thread_id, model: ...}` | Save `thread_id` to chat session. |
| `item.completed` (`agent_message`) | `text {text: item.text}` | Text response from agent. |
| `item.started` (`command_execution`) | `tool_use {id: item.id, name: "command_execution", input: {"command": item.command}}` | Started command execution. |
| `item.completed` (`command_execution`) | `tool_result {id: item.id, text: item.aggregated_output, is_error: item.exit_code != 0}` | Command completion with output and status. |
| `turn.completed` | `usage {info: item.usage}` then `done {is_error: false}` | Token usage and successful turn termination. |
| `turn.failed` / `error` | `error {message: ...}` then `done {is_error: true}` | Error reporting and failure turn termination. |
| Other `item.*` / `turn.started` | Ignored | Non-visual or internal lifecycle events. |

---

## 6. Windows-Specific Discoveries

1. **UTF-8 Output Encoding**: Codex emits UTF-8 text containing smart quotes and Unicode characters. Subprocess streams must be decoded with `encoding="utf-8"` (or `errors="replace"`), avoiding Python's Windows default `cp1252` encoding which throws `UnicodeDecodeError`.
2. **Directory Trust & Repo Checks**: When running outside Git repositories or in temporary workspaces, `--skip-git-repo-check` is mandatory to avoid `Not inside a trusted directory` errors.
3. **Elevated Sandbox on Windows**: In default configurations, non-elevated temp directories may trigger `UnauthorizedAccessException` or PowerShell policy blocks unless executing in user-trusted directories. Using the workspace folder (`cwd`) avoids this issue.

---

## 7. Recorded Fixtures

Live fixtures saved to `tests/fixtures/codex/`:
- `tests/fixtures/codex/read_only_run.jsonl`: Read-only turn answering "pong" (`-s read-only`).
- `tests/fixtures/codex/command_run.jsonl`: Shell command execution (`echo hello`) under `-s workspace-write` showing `item.started` and `item.completed`.
- `tests/fixtures/codex/resume_run.jsonl`: Session resume using `resume <thread_id>` verifying conversation memory.
- `tests/fixtures/codex/error_run.jsonl`: Error handling on invalid model request.
