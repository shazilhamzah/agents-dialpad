# A3. Rename, pin, search and export chats (and merge-safe saving)

- **Size:** S–M
- **Needs first:** nothing (but B2, B3, B4 and C5 rely on part 1 of this task)
- **Branch:** `feat/a3-chat-housekeeping`
- **PR title:** `feat: rename, pin, search and export chats`

## Goal

1. **Part 1 (do first): merge-safe saving.** A reply that finishes must not overwrite changes made to the chat while it
   was running (for example a rename).
2. Rename a chat.
3. Pin a chat (pinned chats are listed first).
4. Search all chats by title and message text.
5. Export a chat as a Markdown file.

## Why

The chat list grows quickly and titles are just the first message. Users need to tidy it, find old answers, and take a
conversation into notes or an issue.

## Read first

- `agents_dialpad/runs.py` (`start`, `_drive`, especially its `finally:` block)
- `agents_dialpad/store.py`
- `agents_dialpad/app.py` (`ChatPatch`, `patch_chat`, `list_chats`)
- `agents_dialpad/static/app.js`: `renderList()`, `refreshList()`, `buildPane()` (the `#btn-more` menu items), `updateHeader()`, `openSheet()`, `confirmSheet()`
- `tests/test_integration.py`

## Verify first

1. In `runs.py`, `_drive()` currently saves **the `chat` dict it was started with** (`self.store.save(chat)` in `finally`).
   Confirm this. That stale copy is the bug part 1 fixes.
2. `PATCH /api/chats/{id}` currently returns 409 while a run is active. Confirm.

## Steps

### Part 1: merge-safe saving (`runs.py`)

Replace the body of the `finally:` block in `_drive()` with: reload the chat from disk, apply only what the run owns,
save.

```python
finally:
    try:
        fresh = self.store.get(chat["id"])
    except KeyError:
        fresh = None                     # deleted while the reply was running: do not bring it back
    if fresh is not None:
        fresh["messages"].append({"role": "assistant", "run_id": run.id, "events": _compact(run.events), "ts": time.time()})
        if chat.get("session_id"):
            fresh["session_id"] = chat["session_id"]
        fresh["updated"] = time.time()
        self.store.save(fresh)
    await run.finish()                   # keep: after saving, so readers never miss the saved message
```

Remove the old `if self.store.exists(...)` branch (the `try/except KeyError` replaces it). If A1 is merged, keep
`self.keep_awake.release()` as the first line of `finally`.

### Part 2: store

1. `Store.create()` adds `"pinned": False` to new chats.
2. `Store.list()` includes `"pinned": bool(c.get("pinned"))` in each summary and sorts with pinned first, then by
   `updated` descending: `out.sort(key=lambda c: (not c["pinned"], -(c["updated"] or 0)))`.
3. New method:
   ```python
   def search(self, q: str, limit: int = 50) -> list[dict]:
       """Case-insensitive substring match on title, user messages and assistant text. Adds a short 'snippet'."""
   ```
   For each chat file: build the searchable texts: title, every user `text`, and every assistant event of type `text`.
   On the first match, `snippet` = up to 40 characters before and 60 after the match, whitespace collapsed, with `…`
   where cut. Return summaries (same keys as `list()`) plus `snippet`, sorted like `list()`, at most `limit`.
   Skip unreadable files silently.

### Part 3: API (`app.py`)

1. `ChatPatch` gets two fields: `title: str | None = Field(default=None, max_length=80)` and `pinned: bool | None = None`.
2. `patch_chat`:
   - If `body.model is not None` and a run is active → 409 (unchanged behaviour for model).
   - If `body.title is not None`: `t = " ".join(body.title.split())`; empty → 400 `"Title can't be empty"`; set `chat["title"] = t`.
   - If `body.pinned is not None`: set `chat["pinned"] = body.pinned`.
   - Title and pinned are allowed **while a run is active** (part 1 makes that safe).
   - Return `{"model": ..., "title": ..., "pinned": ...}`.
3. `list_chats` gets `q: str = Query(default="", max_length=100)`: empty → `store.list()`; otherwise `store.search(q)`.
   Keep adding `running` to each item.
4. Export: new module `agents_dialpad/export.py`:
   ```python
   def chat_to_markdown(chat: dict, agent_label: str) -> str: ...
   def filename_for(chat: dict) -> str: ...   # "my-chat-title.md": lowercase, [a-z0-9-], max 40 chars, fallback "chat.md"
   ```
   Markdown layout:
   ```text
   # <title>

   - Agent: <agent_label>   - Model: <model or "default">   - Project: <project>   - Started: <ISO date of created>

   ## You
   <user text>

   ## <agent_label>
   <assistant text events joined>
   - Tool: `<name>` `<arg>` (ok | failed)        <- one line per tool_use, in order
   > Blocked (needed approval): <denials>        <- only if the done event has denials
   ```
   Route: `GET /api/chats/{chat_id}/export` returns
   `Response(content=md, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename_for(chat)}"'})`.
   For the tool argument, reuse the same idea as `toolArg()` in `app.js` (command, file_path, path, pattern, url, query), truncated to 80 characters.

### Part 4: UI (`app.js`, `style.css`)

1. Icons to add to `ICON` (24x24, same style): `pin` (`<path d="M12 17v5M9 10.76V6h6v4.76l2 2.24v2H7v-2z"/><path d="M9 6V3h6v3"/>`),
   `edit` (`<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>`),
   `download` (`<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>`), `search` (`<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>`).
2. Chat "More" menu (in `buildPane`): items in this order: **Rename**, **Pin** / **Unpin** (label depends on
   `cur.chat.pinned`), **Export as Markdown**, **Usage limits**, **Delete chat** (danger, stays last).
3. Rename: `openSheet` with a form: label "Chat name", `<input id="r-title" type="text" maxlength="80">` pre-filled,
   buttons Cancel / Save. On Save: `PATCH {title}`; set `cur.chat.title`; `updateHeader()`; `refreshList()`.
4. Pin: `PATCH {pinned: !cur.chat.pinned}`; update `cur.chat.pinned`; `toast(pinned ? 'Pinned' : 'Unpinned')`; `refreshList()`.
5. Export: `const r = await api('/chats/' + id + '/export'); const blob = await r.blob();` filename from the
   `Content-Disposition` header (fallback `chat.md`); create an `<a download>` with `URL.createObjectURL(blob)`, click
   it, remove it, revoke the URL after 10 s.
6. Search box: in `mountShell()`, put this between the sidebar header and `#chat-list`:
   `<div class="search">${icon('search')}<label class="sr" for="q">Search chats</label><input id="q" type="search" placeholder="Search chats" autocomplete="off" enterkeyhint="search"></div>`.
   - `state.query` holds the current text. On `input`, debounce 250 ms: empty → `renderList()` from `state.chats`;
     otherwise `getJSON('/chats?q=' + encodeURIComponent(q))` and render the results with the snippet under the title.
   - `refreshList()` must not overwrite the list while `state.query` is non-empty.
   - No results: show "No chats match “<query>”." (escaped).
7. Pinned rows: in `renderList()`, when there are pinned chats, render a small label "Pinned" before them and "Recent"
   before the rest (sentence case, muted, 13 px, not uppercase). Show `icon('pin')` at the end of pinned rows (decorative, `aria-hidden`).
8. CSS for `.search`: a 44 px tall field with the icon inside on the left, full width, 12 px side padding, uses
   `--surface`, `--control` border, `:focus-within` ring like `.field`.

## Tests (`tests/test_integration.py` unless noted)

1. `test_renaming_while_a_reply_runs_is_not_lost`: send `"SLOW"`; PATCH title "Renamed"; stop; wait until idle;
   GET chat → title is "Renamed" **and** it has the assistant message.
2. `test_rename_validates_the_title`: empty / whitespace → 400; 81 characters → 422 or 400; normal → 200.
3. `test_model_change_is_still_refused_while_running`: 409.
4. `test_pinned_chats_come_first`: create A, B, C; pin A; list order starts with A.
5. `test_search_finds_titles_and_message_text`: chat with a reply containing "pong" → `?q=pong` finds it with a
   snippet; `?q=zzz` returns an empty list.
6. `test_export_returns_markdown_with_the_conversation`: header `content-disposition` has `.md`; body starts with `# `;
   contains `## You` and the user text.
7. `test_deleted_while_running_stays_deleted` (already exists as `test_deleting_a_running_chat_does_not_bring_it_back`): must still pass.
8. Unit tests in `tests/test_export.py`: `filename_for` with unicode, slashes and empty titles; tool lines and denials
   appear in the Markdown.

## Manual check

Rename during a running reply; pin and unpin; search on a phone width (the keyboard must not cover results); export on
desktop (file downloads) and iPhone (share sheet opens). Check 320 / 375 / 768 / 1280 px, light and dark.

## Docs

README: a short "Organising chats" section. CHANGELOG (Added + Fixed: "a finishing reply no longer overwrites changes made meanwhile").

## Acceptance checklist

- [ ] Part 1 test passes, and all existing tests still pass.
- [ ] Rename, pin, search and export work from the UI.
- [ ] Search never freezes the list polling, and the polling never wipes search results.
- [ ] Exported Markdown contains no HTML and no token.

## Pitfalls

- `store.search` reads every chat file; that is fine for hundreds of chats. Do not add an index.
- Do not use `Markdown.render()` for snippets: they are plain text, use `esc()`.
