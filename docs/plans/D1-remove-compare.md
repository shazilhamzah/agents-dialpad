# D1. Remove the compare feature

- **Size:** S–M
- **Needs first:** PR #5 merged (this removes code that PR adds)
- **Branch:** `chore/d1-remove-compare`
- **PR title:** `chore: remove the compare-agents view`

## Goal

Take out "Ask two agents at once" (task C5) completely: the "Compare: A + B" options in the New chat sheet, the
`#/g/<group>` route and its two-column view, the `/api/groups/...` routes and the `group` field on new chats. The app goes
back to one chat on screen at a time.

Chats that were created as part of a compare group are **not deleted**. They show up as ordinary chats in the list.

## Why

The owner does not use it, and it doubled the complexity of the chat screen (two views, shared composer, tab bar,
"is either one running" checks). Removing it makes the next tasks (D2, D4, D5) simpler and safer.

## Read first

- `agents_dialpad/app.py`: `GROUP_RE`, `NewChat.group`, `create_chat`, `get_group`, `delete_group`
- `agents_dialpad/store.py`: `create(..., group=None)`, `list()`, `search()`
- `agents_dialpad/static/app.js`: `curGroup`, `activeViews`, `openNewChat` (`pairs`, `pairOf`, `sharedModes`),
  `renderList` (compare rows), `openGroup`, `buildGroupPane`, `sendMessage(views)`, the router near the end of the file
  (`const mg = location.hash.match(/^#\/g\/...`), `teardownChat`, `createChatView` (`activeViews.length <= 1` checks)
- `agents_dialpad/static/style.css`: the `/* compare view */` block
- `tests/test_integration.py`: `test_group_*`, `test_compare_group_holds_two_chats`
- `README.md` "Compare agents" section, `CHANGELOG.md`, `docs/plans/C5-compare-agents.md`

## Verify first

1. `git grep -n -i -E "group|compare|activeViews|pairOf|sharedModes" -- agents_dialpad tests` and keep the list. Every hit
   must be either removed by this task or be one of the unrelated uses below. Stop and report anything else.
2. Unrelated uses of the word "group" that must **stay**: `alerts.py` (limit rows have a `group` such as
   "Gemini Models") and the Limits sheet in `app.js`. Do not touch them.

## Steps

### 1. Server

1. `app.py`: delete `GROUP_RE`, the `group` field of `NewChat`, the two `group` checks in `create_chat`, and the routes
   `GET /api/groups/{group}` and `DELETE /api/groups/{group}`.
2. `store.py`: remove the `group` parameter of `create()` and stop writing `"group"` into new chats. Remove `"group"` from
   the keys copied in `list()` and `search()`. Old chat files that still contain `"group"` must keep loading (just ignore
   the key; do not rewrite files).
3. Old requests that still send `group` in `POST /api/chats`: pydantic ignores unknown fields by default. Check that
   `NewChat` does not forbid extra fields; a cached old app on a phone must still be able to start a normal chat.

### 2. Web app

1. `openNewChat`: delete the compare options (`pairs`, `pairOf`, `sharedModes`) and the compare branch in `onsubmit`.
   The agent `<select>` lists only real agents again. When the agent changes, the model and permission lists follow that
   agent (this code already exists for the single-agent case; keep it).
2. `renderList`: remove the compare row (`href="#/g/..."`). Every chat renders as a normal row.
3. Delete `curGroup`, `openGroup`, `buildGroupPane`, the `#/g/` route in the router and the `group_` draft key.
   An old bookmark to `#/g/<id>` must fall through to the chat list (`#/`), not show an error.
4. `activeViews`: the chat screen now always has exactly one view. Replace `activeViews` with `cur` everywhere:
   `sendMessage(views)` becomes `sendMessage(view)`; the `activeViews.length <= 1` checks in `createChatView` go away
   (always true); the stop/send button uses `cur` only. Keep `createChatView` itself: it is the single chat view.
5. `style.css`: delete the `/* compare view */` block and any `.col`, `.col-head`, `.compare` rules.
6. Keep `this.els.thread.dataset.chatId` in `renderThread` (the approval buttons use it) but update its comment.

### 3. Tests

1. Delete `test_group_chats_are_linked_and_listed`, `test_group_id_is_validated`, `test_unknown_group_is_404`,
   `test_compare_group_holds_two_chats`.
2. Add:
   - `test_groups_api_is_gone`: `GET /api/groups/abcd1234` returns 404.
   - `test_old_clients_sending_group_still_get_a_normal_chat`: `POST /api/chats` with `"group": "abcd1234"` → 200, and
     the saved chat has no `group` key.
   - `test_chats_from_old_compare_groups_still_list`: write a chat file containing `"group": "abcd1234"` directly into
     the chats folder; `GET /api/chats` lists it and `GET /api/chats/<id>` opens it.

### 4. Browser check (by hand, at 375 px and 1280 px wide)

New chat sheet shows only Claude Code / Antigravity / Codex; a chat starts, sends, stops; switching between two chats
quickly keeps each chat's draft; an old `#/g/abcd1234` URL lands on the list; no console errors.

## Docs

- `README.md`: delete the "Compare agents" section and any feature-list line about it.
- `CHANGELOG.md` (Unreleased): "Removed: the compare-agents view. Chats created with it remain as normal chats."
- `docs/plans/README.md`: mark C5 as removed (see the table).
- Add a note at the top of `docs/plans/C5-compare-agents.md`: "Removed in D1. Kept for history."

## Acceptance checklist

- [x] No compare UI, route or API remains (`git grep -n -i compare -- agents_dialpad` finds nothing).
- [x] Old compare chats still open as normal chats.
- [x] A cached old app that sends `group` can still start a chat.
- [x] All tests pass on Windows, macOS and Linux CI.
