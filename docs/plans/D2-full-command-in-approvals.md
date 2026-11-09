# D2. Show the full command on approval cards

- **Size:** S
- **Needs first:** nothing (D1 first is easier, because the chat screen then has one view)
- **Branch:** `fix/d2-approval-details`
- **PR title:** `fix: show the full command (and what it is for) on approval cards`

## Goal

When an agent asks "Allow this?", the card shows **everything needed to decide**: the whole command (wrapped over as many
lines as it needs, never cut off with "…"), the agent's one-line reason when it gives one, and, for file edits, which
file and what changes. Long commands are collapsed to about 6 lines with a **Show all** button. A **Copy** button copies
the full command.

## Why

1. The card shows the command on one line with `text-overflow: ellipsis` (`.approval-tool .arg` in `style.css`). On a
   phone that is about 35 characters. A command like `rm -rf build && npm ci && npm run deploy -- --prod` shows as
   `rm -rf build && npm ci && npm run…`, and the dangerous part is hidden. You cannot safely press Allow.
2. **Bug:** Antigravity approval cards show no command at all. `providers/antigravity.py` sends
   `{"type": "approval", "command": ..., "description": ...}`, but the web app reads `toolArg(ev.input)`, and Antigravity
   events have no `input`. So the card shows only the tool name.

## Read first

- `agents_dialpad/providers/claude.py` (the `control_request` → `approval` event), `agents_dialpad/providers/antigravity.py`
  (`session/request_permission` → `approval` event), and the fixtures in `tests/fixtures/claude_control/` and
  `tests/fixtures/agy_acp/`.
- `agents_dialpad/static/app.js`: `toolArg`, `assistantHTML` (the `approval` block), the approval click handler
  (`/* ---- approval buttons (Allow / Deny) ---- */`), `copyText`.
- `agents_dialpad/static/style.css`: `/* approvals */`.

## Verify first

Open the recorded fixtures and write down, for each provider, where the command text and the reason live. Expected:

| Provider | Command | Reason / description | Other inputs |
|---|---|---|---|
| Claude Code | `request.input.command` (Bash); `input.file_path` for Edit/Write | `request.description` (may be missing) | `input.old_string`/`new_string` (Edit), `input.content` (Write) |
| Antigravity | `params.toolCall.rawInput.CommandLine` | `rawInput.toolSummary` or `toolCall.title` | rest of `rawInput` |

If a fixture shows something different, stop and report it.

## Steps

### 1. One approval event shape for every provider (server)

Every provider yields:

```python
{
    "type": "approval",
    "id": "<request id>",
    "tool": "Bash",                 # tool name as the agent reports it
    "command": "full text",         # the thing being approved, as one string ("" if none)
    "description": "why, if given", # "" if none
    "input": {...},                 # the raw tool input (dict), for details; {} if none
    "truncated": False,             # True if command or input was shortened (see the limit below)
}
```

1. Add `approval_event(req_id, tool, raw_input, description)` in a new small module `agents_dialpad/approvals.py`
   (pure function, easy to test). It picks `command` from the first non-empty of: `command`, `CommandLine`, `cmd`,
   `file_path`, `path`, `url`, `pattern`, `query`; otherwise `json.dumps(raw_input, ensure_ascii=False)`.
2. **Size limit:** cap `command` at 20 000 characters and every string inside `input` at 20 000 characters
   (set `truncated: True` when anything was cut). This keeps saved chats small and the phone fast.
3. Use it in `claude.py` (tool = `tool_name`, raw input = `input`, description = `description`) and in `antigravity.py`
   (tool = `toolCall.name`, raw input = `rawInput` or `args`, description = `toolSummary` or `title`). Keep the extra
   `req_id` key that Antigravity sends today only if something reads it (`git grep req_id`); otherwise drop it.
4. Codex has no approvals (see C2); nothing to change there.

### 2. Card UI (web app)

In `assistantHTML`, the approval block becomes:

```text
Allow this?
<description, if any>                                  (normal text, --text-2)
┌──────────────────────────────────────────────┐
│ $ Bash                                 [Copy] │  (tool name + copy button)
│ rm -rf build && npm ci &&                     │  (<pre>, wraps, monospace)
│ npm run deploy -- --prod                      │
│ … Show all (14 lines)                         │  (only when longer than 6 lines)
└──────────────────────────────────────────────┘
File: src/app.ts                                      (Edit/Write only)
- old line                                            (Edit: old_string as "-" lines, new_string as "+")
+ new line                                            (Write: first 20 lines of content as "+")
Details ▸                                             (<details>: the rest of `input` as pretty JSON)
[ Allow ]  [ Deny ]
```

1. Read `ev.command ?? toolArg(ev.input)` so chats saved before this change still show something.
2. The command is a `<pre class="approval-cmd">` with `white-space: pre-wrap; overflow-wrap: anywhere;`. Remove the
   ellipsis rules for approvals (keep them for ordinary tool rows).
3. Collapsing: if the command has more than 6 lines or more than 400 characters, add class `clamped`
   (`max-height: 9.5em; overflow: hidden` with a fade at the bottom) and a **Show all** button that removes the class.
   Remember expanded cards in a `Set` (like `state.openTools`) so a re-render does not collapse them again.
4. **Copy** uses the existing `copyText`. Give the button `aria-label="Copy command"`.
5. For `tool` Edit/MultiEdit/Write, render the file path and the small diff described above, reusing the diff line
   styles from the Changes viewer (B2). Escape everything with `esc`.
6. If `ev.truncated`, show a note: "Very long. The rest is cut off here; Deny if unsure."
7. Allow/Deny buttons stay at least 44 px tall and stay visible without scrolling inside the card (the command area
   scrolls, not the buttons). Keep the buttons below the command so the user reads before tapping.

### 3. Tests

- `tests/test_approvals.py` (new, unit): `approval_event` picks `command` for Bash, `CommandLine` for Antigravity,
  `file_path` for Edit, JSON for unknown input; truncation sets `truncated` and keeps exactly 20 000 characters.
- `tests/test_parsers.py`: the Claude and Antigravity fixtures produce events with non-empty `command` and the expected
  `description`.
- `tests/test_integration.py`: with the fake Antigravity ACP agent, the approval event stored in the chat has a
  non-empty `command` (this is the regression test for the blank-card bug).
- `tests/js/`: if the markdown test setup allows it, add a test that a 30-line command renders fully inside the `<pre>`
  (no "…"). Otherwise check it by hand (below).

### 4. Browser check (by hand, at 375 px)

Use the fake Claude agent with a prompt containing `NEEDS_APPROVAL` after extending `tests/fake_agents/fake_claude.py`
so it can send a long multi-line command when the prompt contains `LONG_COMMAND`. Check: the full command is readable,
Show all expands it, Copy copies all of it, Allow/Deny still work, and the page does not scroll sideways.

## Docs

`README.md` permissions section: one sentence that the approval card shows the full command and the agent's reason.
`CHANGELOG.md`: "Fixed: approval cards cut long commands off, and showed nothing for Antigravity."

## Acceptance checklist

- [x] A 500-character command is fully readable on a 375 px screen.
- [x] Antigravity approval cards show the command.
- [x] Old saved chats with approval cards still render.
- [x] No unescaped agent text reaches `innerHTML`.
