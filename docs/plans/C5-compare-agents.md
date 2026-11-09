# C5. Ask two agents at once

- **Size:** M–L (two parts)
- **Needs first:** A3
- **Branches:** `refactor/c5-chat-view`, then `feat/c5-compare`
- **PR titles:** `refactor: make the chat view reusable` and `feat: ask two agents the same question`

## Goal

In the new-chat sheet, the agent list gets **Both (compare)** when two or more agents are available. It creates two
linked chats (same project, same permission level), and opens a compare view: on phones, a two-tab switch
(Claude Code | Antigravity); from 1000 px wide, the two conversations side by side. One message box sends the same
message to both.

## Why

People already copy the same question into two tools to compare answers.

## Read first

`agents_dialpad/static/app.js` in full, especially `cur`, `buildPane()`, `renderThread()`, `renderLive()`, `attach()`,
`recover()`, `sendMessage()`, `setRunning()`, `scrollToEnd()`. This task changes how they hold state.

---

## Part 1: refactor (no behaviour change)

Today the open conversation lives in the single global `cur`, and the render functions find their elements with fixed
ids (`#thread`, `#live`, `#msgs`, `#send`). Turn that into an object that owns its own elements.

1. Create `function createChatView(chat, els)` returning an object with:
   - state: `chat`, `live`, `ctrl`, `gen`, `openTools`, `stick`;
   - elements in `els`: `{ msgs, thread, jump, send (optional), sr }`;
   - methods: `renderThread()`, `renderLive()`, `scheduleRender()`, `scrollToEnd(force)`, `attach()`, `recover()`,
     `setRunning(on)`, `stop()`, `destroy()` (aborts the stream).
   Move the bodies of today's functions into these methods, replacing `$('#thread')` with `els.thread` and so on, and
   `cur.` with `this.`/the closure variables.
2. `buildPane()` creates one view: `cur = createChatView(chat, {...})`. Everything that used `cur.chat` keeps working.
3. `sendMessage()` takes the view: `sendMessage(view)`.
4. The global `visibilitychange` handler calls `recover()` on every live view.

**Test this part by hand before opening the PR** (there are no automated browser tests yet): open a chat, send, stop,
reload mid-reply (it must re-attach), lock the phone mid-reply and come back, switch chats on a wide screen while a
reply runs, rename (A3), Changes (B2) if present. Everything must behave exactly as before. List what you checked in the PR.

## Part 2: compare view

### Server

1. Chats get an optional `group` (8 lowercase hex). `NewChat` accepts `group: str | None` (validated with a regex).
   `Store.list()` includes it.
2. `GET /api/groups/{group}` → the chats in that group (404 if none).

### UI

1. New-chat sheet: if 2+ agents are available, add an option **Both (compare)** at the end of the agent select. When
   chosen, hide the model select (each agent uses its default model) and on Start: generate a group id
   (`crypto.getRandomValues`, 8 hex), create one chat per available agent with that group, then
   `location.hash = '#/g/' + group`.
2. Route `#/g/<group>`: fetch the group, build the pane:
   - header: title "Compare", subtitle "<project> · <permission>", More menu with Delete both;
   - a segmented control (`role="tablist"`, two `role="tab"` buttons, 44 px) shown below 1000 px wide;
   - two columns, each with its own `.msgs`/`.thread` and a small heading with the agent name; on narrow screens only
     the selected tab's column is visible (`hidden` attribute), on wide screens both;
   - one composer. Send posts the same text to both chats, then calls `attach()` on both views.
   - the tab of an agent that is still replying shows a small activity dot.
3. In the chat list, chats of a group are shown as one row "Compare: <title>" that opens the group route.
4. CSS: `.compare { display: grid; grid-template-columns: 1fr; } @media (min-width: 1000px) { .compare { grid-template-columns: 1fr 1fr; } }`
   with a 1 px `--line` divider between columns.

## Tests

Server: `test_group_chats_are_linked_and_listed`, `test_group_id_is_validated`, `test_unknown_group_is_404`.
UI: manual checklist at 375 px and 1280 px: both replies stream at the same time; switching tabs mid-reply keeps both
streams; Stop stops both; reload re-attaches both.

## Docs

README: "Compare agents". CHANGELOG.

## Acceptance checklist

- [x] Part 1 merged on its own with a manual checklist showing no behaviour change.
- [x] Both replies stream simultaneously and survive a reload.
- [x] Deleting a compare group deletes both chats (with confirmation).
