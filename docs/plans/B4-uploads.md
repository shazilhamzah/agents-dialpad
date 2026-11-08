# B4. Upload screenshots and files to a chat

- **Size:** M
- **Needs first:** A3
- **Branch:** `feat/b4-uploads`
- **PR title:** `feat: attach screenshots and files to a message`

## Goal

A paperclip button next to the message box lets the user attach up to 10 files (screenshots, PDFs, logs, text). They
upload immediately, show as chips (with thumbnails for images), and are sent with the next message. The agent is told
where the files are and is allowed to read them.

## Why

"Here's the error on my screen" is the most natural thing to send from a phone.

## Design

- Files are stored **outside** the project: `<data>/uploads/<chat-id>/<8 hex>-<safe name>`, so they never end up in a
  git commit by accident.
- The agent gets access with each CLI's `--add-dir <that folder>` (both `claude` and `agy` support `--add-dir`).
- The prompt gets a short appendix listing the absolute paths.

## Read first

- `agents_dialpad/app.py` (`NewMessage`, `send_message`, `delete_chat`), `agents_dialpad/runs.py` (`start`, `_drive`)
- `agents_dialpad/providers/claude.py`, `agents_dialpad/providers/antigravity.py` (`stream()` argument lists)
- `tests/fake_agents/*.py`
- `agents_dialpad/static/app.js` (`buildPane` composer, `sendMessage`, `msgHTML`)

## Verify first

1. `claude --help` and `agy --help` both list `--add-dir`. (They did when this plan was written.)
2. With a real `claude` in read-only mode, `--add-dir <folder>` lets it read an image placed in that folder when asked
   "describe the image at <path>". Note the result in the PR. If it cannot read images, still ship the feature for
   text files and state the limitation in the README.

## Limits

- 15 MB per file, 10 files per message, 200 MB per chat.
- Allowed extensions: `png jpg jpeg gif webp heic pdf txt md csv json log yaml yml xml html css js ts py`. Others → 415.

## Steps

### 1. Storage module `agents_dialpad/uploads.py`

```python
def upload_dir(chat_id: str) -> Path:                 # config.DATA / "uploads" / chat_id  (chat_id already validated)
def safe_name(name: str) -> str:                       # keep [A-Za-z0-9._-], collapse others to '-', max 80, keep extension, fallback "file"
def save(chat_id: str, name: str, data: bytes) -> dict # returns {"name": stored_name, "size": n}; enforces type + per-chat total
def resolve(chat_id: str, names: list[str]) -> list[Path]   # each must exist inside upload_dir(chat_id); ValueError otherwise
def remove_all(chat_id: str) -> None                   # shutil.rmtree(..., ignore_errors=True)
```

### 2. Route: upload

`PUT /api/chats/{chat_id}/uploads?name=<original file name>` with the raw file as the body (no multipart, so no extra
dependency):

```python
@api.put("/chats/{chat_id}/uploads")
async def upload(chat_id: str, request: Request, name: str = Query(..., min_length=1, max_length=200)):
    chat_or_404(chat_id)
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_FILE: raise HTTPException(413, "That file is larger than 15 MB")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_FILE: raise HTTPException(413, "That file is larger than 15 MB")
    return uploads.save(chat_id, name, bytes(data))    # 415 on bad type, 413 if the chat total is exceeded
```

### 3. Sending with attachments

1. `NewMessage` gets `attachments: list[str] = Field(default_factory=list, max_length=10)`.
2. `send_message`: `paths = uploads.resolve(chat_id, body.attachments)` (400 on `ValueError`), then
   `runs.start(chat, body.text, attachments=paths)`.
3. `RunManager.start(chat, text, attachments=())`:
   - store the user message as `{"role": "user", "text": text, "attachments": [p.name for p in attachments], "ts": ...}`;
   - the prompt sent to the agent is `text` plus, if any, `"\n\nAttached files (read them from these paths):\n" + one "- <absolute path>" per line`;
   - pass `add_dirs=[str(upload_dir)]` through to the provider when there are attachments **or** the folder exists
     (so follow-up questions about earlier files still work).
4. Providers: `stream(self, chat, prompt, cwd, run, instructions="", add_dirs=())`. Claude: append
   `["--add-dir", d]` per folder. Antigravity: same flag. Update both fakes to record `--add-dir` values in `FAKE_LOG`
   (they already log the full argv, so just make sure parsing does not break on the new flags).
5. `delete_chat` calls `uploads.remove_all(chat_id)` after deleting the chat.

### 4. UI

1. Composer: a 44 px `icon-btn` with icon `clip` (`<path d="m21 12-8.5 8.5a6 6 0 0 1-8.5-8.5l9-9a4 4 0 0 1 5.66 5.66l-9 9a2 2 0 0 1-2.83-2.83L15 7"/>`)
   to the left of the text field, `aria-label="Attach files"`, plus a hidden
   `<input type="file" multiple accept="image/*,.pdf,.txt,.md,.csv,.json,.log,.yaml,.yml,.xml,.html,.css,.js,.ts,.py">`.
2. `uploadFile(chatId, file)`: **do not use `api()`** (it forces a JSON content type). Use
   `fetch('/api/chats/' + id + '/uploads?name=' + encodeURIComponent(file.name), { method: 'PUT', headers: { Authorization: 'Bearer ' + token, 'Content-Type': file.type || 'application/octet-stream' }, body: file })`,
   handle 401 like `api()` does, and show the server's `detail` on errors.
3. Pending attachments live in `cur.pending = [{name (stored), label (original), url (object URL for images)}]`. Render
   chips above the text field: thumbnail (images) or a file icon, the original name (ellipsis), and a remove button
   (`aria-label="Remove <name>"`; removing only drops it from the message; the file stays until the chat is deleted).
4. While any upload is in progress, the Send button is disabled and the chip shows a spinner.
5. `sendMessage()` includes `attachments: cur.pending.map(p => p.name)`, then clears `cur.pending` and revokes object URLs.
6. `msgHTML()` for user messages with `attachments`: under the bubble text, a small list of file names with the clip icon.
7. A message with attachments but empty text is allowed: the text becomes "See the attached files." (client side).

## Tests

`tests/test_uploads.py` (unit): safe names (`../../x.png`, unicode, very long, no extension), type check, size totals,
`resolve` rejects names from another chat or with path separators, `remove_all`.

`tests/test_integration.py`:
1. `test_upload_then_send_gives_the_agent_access` (fake claude argv has `--add-dir <uploads/chat>`; prompt contains the absolute path).
2. `test_upload_limits` (413 too big, 415 bad type).
3. `test_attachments_must_belong_to_the_chat` (400).
4. `test_deleting_a_chat_removes_its_uploads`.
5. `test_antigravity_also_gets_the_folder`.
6. `test_upload_needs_the_token`.

## Manual check

iPhone: attach a screenshot from Photos (iOS usually converts HEIC to JPEG for web uploads; note what happens),
send "what's in this screenshot?". Android: same. Desktop: drag-and-drop is not required. Check the chips at 320 px.

## Docs

README: "Attachments" section with limits and where files are stored. SECURITY.md: uploaded files are stored
unencrypted in the data folder and are readable by the agent. CHANGELOG.

## Acceptance checklist

- [ ] Files never land inside the project folder.
- [ ] The agent can read attached text files (and images, if the verify step showed it can).
- [ ] All limits enforced server-side, not only in the browser.
- [ ] Deleting a chat deletes its uploads.

## Pitfalls

- `request.stream()` must be consumed with the size check inside the loop, or a huge upload fills memory.
- Never trust the browser's file name or MIME type; check the extension server-side after `safe_name`.
