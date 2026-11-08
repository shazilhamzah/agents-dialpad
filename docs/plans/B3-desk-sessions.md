# B3. Continue desktop sessions on the phone (and back)

- **Size:** M
- **Needs first:** A3
- **Branch:** `feat/b3-desk-sessions`
- **PR title:** `feat: continue Claude Code desktop sessions from the phone`

## Goal

1. In the new-chat sheet, a **Continue a desktop session** option lists the recent Claude Code sessions that were
   started in the chosen project folder on the computer. Picking one creates a chat that resumes that session
   (`claude --resume <id>`), so the agent remembers everything from the desk.
2. In a Claude chat, **More → Continue on the computer** shows the exact terminal command to resume the same session at
   the desk, with a Copy button.

Claude Code only. (Antigravity has no documented way to list sessions; out of scope.)

## Why

People start work at the desk and want to keep going from the sofa, and the other way round.

## What we know about the files (observed on a real machine)

- Claude Code stores each session as `~/.claude/projects/<folder-name>/<session-uuid>.jsonl`. The folder name is the
  working directory with separators replaced; **do not rely on that encoding**: read the `cwd` field instead.
- Each line is a JSON record. Early lines can be `{"type": "queue-operation", ...}` with no `cwd`. Later records have
  `type` (`user`, `assistant`, `attachment`, …), `cwd`, `sessionId`, `timestamp`, `isSidechain`, and for user
  records a `message` whose `content` is either a string or a list of `{type: "text", text}` / `{type: "tool_result", ...}` items.

## Read first

- `agents_dialpad/store.py`, `agents_dialpad/app.py` (`create_chat`), `agents_dialpad/providers/claude.py` (how `--resume` is used)
- `agents_dialpad/static/app.js` (`openNewChat`, `buildPane` menu)

## Verify first

1. Open one of your own `~/.claude/projects/*/*.jsonl` files and confirm the record fields above (look only at keys,
   not at your conversation content).
2. Find out whether Claude Code honours a `CLAUDE_CONFIG_DIR` environment variable for the config folder (check
   `claude --help` and the official docs). If it does, the projects folder is `$CLAUDE_CONFIG_DIR/projects`.
   Write the answer in the PR. Either way, support: env var if set, else `~/.claude`.

## Steps

### 1. New module `agents_dialpad/desk.py`

```python
MAX_FILES = 500          # newest session files scanned
MAX_LINES = 200          # lines read per file while looking for cwd and the first user message
PREVIEW = 120            # characters

def claude_projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"

def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))

def _first_user_text(record: dict) -> str | None:
    """Plain text of a user message; None for tool results, sidechains, or text starting with '<' (command/system markup)."""

def list_sessions(project_path: str, exclude_ids: set[str], limit: int = 20) -> list[dict]:
    """[{"id", "updated" (epoch seconds, file mtime), "preview"}], newest first.
    Scan the newest MAX_FILES *.jsonl files under claude_projects_dir()/*/. For each, read up to MAX_LINES lines:
    skip lines that are not JSON; the first record with "cwd" decides the project (skip the file if it does not match);
    the first user text becomes the preview. Skip files with no user text, files whose stem is not a UUID, and ids in exclude_ids."""

def session_belongs_to(project_path: str, session_id: str) -> bool:
    """True if a file named <session_id>.jsonl exists under claude_projects_dir() and its first cwd matches project_path."""
```

### 2. Routes (`app.py`)

- `GET /api/projects/{project}/desk-sessions` → `list_sessions(path, exclude_ids={chats' session_ids})`. 404 unknown project.
- `POST /api/chats/import` body `{"project", "session_id", "mode": "readonly"}`:
  - project must exist; `session_id` must match `^[0-9a-f-]{36}$`; mode must be allowed (same rules as create);
  - `session_belongs_to()` must be true, else 404 `"That desktop session was not found for this project"`;
  - create a chat with provider `claude`, set `chat["session_id"] = session_id`, `chat["title"]` = preview (48 chars) or
    `"Desktop session"`, `chat["imported"] = True`; save; return it.
- `GET /api/info` adds `"server_os": "windows" | "macos" | "linux"`.

### 3. UI

1. New-chat sheet: when the selected agent is Claude Code, show a secondary button **Continue a desktop session**
   under the form. It opens a second sheet: project select (same list), then the sessions for that project as rows
   (preview text, escaped; "2h ago"), plus the permission select. Tapping a row → `POST /chats/import` → open the chat.
   Empty list: "No desktop sessions found for this folder."
2. Imported chat with no messages: show a muted note at the top of the thread: "Continued from a session on the computer.
   Earlier messages stay there, but the agent remembers them."
3. Chat More menu (Claude chats that have a `session_id`): **Continue on the computer** (icon `term`) → sheet with:
   - Windows: `cd /d "<project path>" && claude --resume <id>`
   - macOS/Linux: `cd '<project path>' && claude --resume <id>` (escape single quotes as `'\''`)
   - Copy button and the note "Run this in a terminal on the computer. Close the chat here first so both don't write at once."
   The project path comes from the chat itself: `GET /api/chats/{id}` adds `"project_path"` (the resolved folder of
   the chat's project). It is only returned to an authenticated caller.

## Tests

`tests/test_desk.py` (set `CLAUDE_CONFIG_DIR` to `tmp_path` with monkeypatch and write fake session files):
1. `test_lists_sessions_for_the_matching_folder_only`.
2. `test_preview_is_the_first_real_user_message` (skips queue-operation lines, tool results, `<command-name>` text, sidechains).
3. `test_newest_first_and_limit`.
4. `test_excluded_ids_are_skipped`.
5. `test_garbage_lines_and_non_uuid_files_are_ignored`.
6. `test_session_belongs_to_checks_the_folder`.

`tests/test_integration.py`:
7. `test_import_creates_a_chat_that_resumes_the_session` (fake claude: the next turn's argv has `--resume <id>`).
8. `test_import_rejects_unknown_or_foreign_sessions`.
9. `test_desk_sessions_need_the_token`.

## Manual check

Start a Claude Code session in a project folder on the computer, say "remember the word kiwi", exit. On the phone:
New chat → Continue a desktop session → pick it → ask "what was the word?". Then More → Continue on the computer, run
the command at the desk, and check the phone's question and answer are in that session.

## Docs

README: "Continue between desk and phone" section. CHANGELOG (Added). SECURITY.md: the phone can list previews of
local Claude sessions for configured project folders only.

## Acceptance checklist

- [ ] Only sessions whose `cwd` is a configured project folder are listed or importable.
- [ ] Previews are plain text, escaped, max 120 characters.
- [ ] Imported chats resume the right session (test 7).
- [ ] Scanning is bounded (MAX_FILES, MAX_LINES) and never crashes on bad files.

## Pitfalls

- On Windows, compare paths case-insensitively (`os.path.normcase`) and resolve short names (`MUHAMM~1`) with `realpath`.
- Do not load whole session files into memory; read line by line and stop early.
