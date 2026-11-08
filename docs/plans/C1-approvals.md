# C1. Approve or deny commands from the phone

- **Size:** L (four parts; hand them over one at a time)
- **Needs first:** nothing for parts 0–1; B1 makes the "needs your approval" notification possible
- **Branches:** `spike/c1-claude-control`, `feat/c1-claude-approvals`, `spike/c1-agy-acp`, `feat/c1-agy-approvals`

## Goal

A new permission level, **Ask me before commands**. When the agent wants to run a command (or do anything else that
needs permission), the reply shows a card with the tool and its arguments and two buttons: **Allow** and **Deny**. The
agent waits for the answer. No answer within 10 minutes counts as Deny. This replaces most uses of "Full access".

## Why

Today, in headless mode, anything needing permission is silently refused ("blocked (needs approval)"). Users either
give up or enable Full access, which is risky.

## What we know (checked when this plan was written)

- `claude --help` lists `--input-format stream-json`, `--permission-prompts <target>` ("who answers permission prompts
  with --print: 'host' (the SDK host or --permission-prompt-tool) or 'none'"), `--permission-prompt-tool` and `--mcp-config`.
  So Claude Code can hand permission questions to the program driving it.
- `agy acp` starts an **Agent Client Protocol** server on stdio. ACP is a JSON-RPC protocol whose agents send
  `session/request_permission` requests to the client.
- **Not yet known:** the exact message shapes for either. Parts 0 and 2 find out. Do not skip them.

---

## Part 0: spike: Claude Code's permission protocol (no product code)

Goal: record real messages, so Part 1 builds on facts.

1. Write `tools/spikes/claude_control.py` (it is not shipped; it can be deleted later). It starts:
   ```text
   claude -p --input-format stream-json --output-format stream-json --verbose
          --permission-mode default --permission-prompts host
   ```
   in an empty temporary folder, keeps **stdin open**, and prints every stdout line with a timestamp.
2. Send one user message on stdin as a single JSON line. Start with this guess and adjust until the CLI accepts it:
   `{"type": "user", "message": {"role": "user", "content": "Run the shell command: echo hello"}}`
3. Watch for a line that asks for permission. The expected shape (**a guess, verify it**) is
   `{"type": "control_request", "request_id": "...", "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {...}}}`.
   If nothing like it appears, try sending an initialize request first (guess:
   `{"type": "control_request", "request_id": "init-1", "request": {"subtype": "initialize"}}`) and repeat. Also check
   the official Claude Code / Claude Agent SDK documentation for "permission prompt tool" and "stream-json input".
4. Answer it. Guess for allow:
   `{"type": "control_response", "response": {"subtype": "success", "request_id": "<same id>", "response": {"behavior": "allow", "updatedInput": <the input you received>}}}`
   and for deny: `... "response": {"behavior": "deny", "message": "The user denied this"}`.
5. Record, in `docs/plans/C1-findings.md`: the exact lines for (a) the permission request, (b) a working allow answer,
   (c) a working deny answer, (d) the final `result` line, (e) how the process ends (does it exit after `result`, or do
   you have to close stdin?), (f) whether `--resume <id>` works together with this mode.
6. If the host protocol cannot be made to work, record why and evaluate the fallback: `--permission-prompt-tool` with a
   tiny MCP server (loaded with `--mcp-config`) whose tool asks our server over HTTP. Record the tool's input and the
   reply format it must return.

**Deliverable:** `C1-findings.md` with real (anonymised) message examples. Also save them as test fixtures in
`tests/fixtures/claude_control/*.jsonl`. Stop here and have the owner review before Part 1.

---

## Part 1: Claude Code approvals

Use the formats recorded in `C1-findings.md`. Where this section shows message shapes, replace them with the recorded ones.

### Server

1. **Mode.** In `app.py` add `{"id": "ask", "label": "Ask me before commands"}` to `BASE_MODES`.
   In `claude.py`, `MODES["ask"] = "default"`.
   Not every agent supports it yet, so make modes **per agent**: give each provider a class attribute
   `supports_ask = True|False` (Claude `True`; Antigravity `False` until Part 3; Codex `False`). `GET /api/info` returns,
   for each provider, `"modes"`: the global modes minus `ask` when unsupported. `create_chat` rejects `ask` for an
   unsupported provider with 400 `"<Agent> can't ask before commands yet"`. In the new-chat sheet, rebuild the
   permission select when the agent select changes, using that provider's `modes`.
2. **Run** (`runs.py`) gets:
   ```python
   self.pending: dict[str, asyncio.Future] = {}
   async def wait_decision(self, req_id: str, timeout: float) -> tuple[bool, str]:   # (allow, "user" | "timeout" | "stopped")
   def decide(self, req_id: str, allow: bool) -> bool:                               # False if unknown or already decided
   ```
   `Run.kill()` resolves every pending future as denied with `"stopped"`.
3. **Provider** (`claude.py`), only when `chat["mode"] == "ask"`:
   - add `--input-format stream-json --permission-prompts host` (plus whatever Part 0 found necessary);
   - write the user message (recorded format) to stdin and **keep stdin open**;
   - when a permission request arrives, `yield {"type": "approval", "id": req_id, "tool": tool_name, "input": input}`,
     then `allow, by = await run.wait_decision(req_id, timeout)`, write the recorded allow/deny answer to stdin, and
     `yield {"type": "approval_result", "id": req_id, "allow": allow, "by": by}`;
   - after the `result` line, close stdin (if Part 0 showed that is needed).
   Other modes keep today's behaviour exactly (prompt on stdin, stdin closed).
4. **Timeout:** `cfg.setdefault("approval_timeout_seconds", 600)`; the env var `AG_APPROVAL_TIMEOUT` overrides it (tests use 1).
5. **Route:** `POST /api/chats/{chat_id}/approvals/{req_id}` with `{"allow": true|false}` → 200; 404 if no active run
   or unknown request; 409 if already decided. `req_id` max 100 characters, `[A-Za-z0-9_-]` only.
6. **Notification:** `RunManager` gets `on_event=None`; `_drive` calls it for `approval` events. In `app.py`, if B1 is
   present, send a push with body "An agent needs your approval" (generic) and the chat URL.

### UI

1. `assistantHTML()` handles `approval`: a card (`.approval`) with "Allow this?" (sentence case), the tool name, and
   the argument (reuse `toolArg()`), escaped. While no `approval_result` with the same id exists **and** the reply is
   live: two buttons, **Allow** (`btn`) and **Deny** (`btn secondary`), with `data-approve="<id>" data-allow="1|0"`.
   After the result: a line "Allowed", "Denied", "No answer in time, so it was denied" or "Stopped".
2. One delegated click handler: `POST /chats/<id>/approvals/<req>`; disable both buttons immediately; on error, toast and re-enable.
3. The live re-render must not lose a click: buttons are re-created on each render, so read the id from the event target
   and ignore clicks on disabled buttons.
4. New chat sheet: the permission select now shows "Ask me before commands" (put it after "Can edit files").

### Fake CLI and tests

1. `tests/fake_agents/fake_claude.py`: when `--input-format stream-json` is present, read the first stdin line as the
   user message. If its text contains `NEEDS_APPROVAL`, print a permission request in the **recorded format**, read the
   next stdin line, and answer `"pong approved"` or `"pong denied"` accordingly, then the `result` line.
2. Tests in `tests/test_integration.py`:
   - `test_ask_mode_waits_and_runs_after_allow`
   - `test_ask_mode_continues_after_deny`
   - `test_unanswered_approval_times_out_as_deny` (`AG_APPROVAL_TIMEOUT=1`)
   - `test_stopping_while_waiting_ends_the_reply`
   - `test_approving_twice_is_409_and_unknown_is_404`
   - `test_approval_route_needs_the_token`
   - `test_other_modes_are_unchanged` (argv for readonly/edit has no `--input-format`)
3. A parser unit test that feeds the recorded fixture lines from Part 0 through the provider's parsing code.

### Manual check

Real `claude`, mode "Ask me before commands", prompt "run `git status`". The card appears on the phone; Allow → the
output appears; repeat with Deny; repeat and wait for the timeout (set 30 s in config for the test).

---

## Part 2: spike: Antigravity over ACP (no product code)

1. Write `tools/spikes/agy_acp.py` that starts `agy acp` and speaks newline-delimited JSON-RPC 2.0 on stdin/stdout.
2. Follow the Agent Client Protocol specification (search for "Agent Client Protocol" by Zed). Expected flow (**verify each step**):
   `initialize` → `session/new` with `{"cwd": "<abs path>", "mcpServers": []}` → `session/prompt` with
   `{"sessionId", "prompt": [{"type": "text", "text": "Run the shell command: echo hello"}]}` → `session/update`
   notifications (message chunks, tool calls) → a `session/request_permission` **request** from the agent with
   `options` (each with an `optionId` and a `kind` like allow-once / reject-once) → answer with the chosen option →
   final response to `session/prompt` with a stop reason.
3. Record in `docs/plans/C1-findings.md`: real examples of each message, how text chunks and tool output arrive, whether
   `session/load` (resume an earlier session) is supported (look at the `initialize` response capabilities), how to
   pick a model, and how the process should be shut down.

Stop and have the owner review.

## Part 3: Antigravity approvals over ACP

Only after Part 2 is approved. Add a new provider path for Antigravity chats in "ask" mode that uses ACP (keep the
current `-p` provider for the other modes). Map ACP updates to our normalised events (`text`, `tool_use`,
`tool_result`, `approval`, `approval_result`, `done`), reuse `Run.wait_decision`, and answer `session/request_permission`
with the allow-once or reject-once option. If `session/load` is not supported, a chat in "ask" mode keeps one `agy acp`
process alive between turns (kill it after 30 minutes idle and on chat delete). Add a fake ACP agent in
`tests/fake_agents/fake_agy_acp.py` that replays the recorded messages, and the same set of tests as Part 1.

---

## Docs

README: "Ask me before commands" in the permissions table and a paragraph on approvals. SECURITY.md: approvals,
timeout, and that "Full access" is still available but rarely needed. CHANGELOG.

## Acceptance checklist

- [x] `C1-findings.md` exists with real recorded messages before any product code.
- [x] Claude "ask" mode works end to end on a real phone.
- [x] Unanswered requests are denied after the timeout; stopping a reply never leaves a process waiting forever.
- [x] Other modes behave exactly as before (test).
- [x] Approval cards escape all text and never show the token.

## Pitfalls

- Never auto-allow. The only ways a request is allowed are an explicit Allow click.
- Keep the provider's stdin writes and stdout reads in one async flow; a blocked write can deadlock the process.
- Messages may arrive split or merged across reads; the provider already reads line by line, keep it that way.
