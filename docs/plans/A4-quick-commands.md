# A4. Quick-command buttons

- **Size:** S–M
- **Needs first:** A3 (menu order); otherwise independent
- **Branch:** `feat/a4-quick-commands`
- **PR title:** `feat: one-tap quick commands defined in the config`

## Goal

The owner lists commands in `config.json`, for example `git status` or `npm test`, globally or per project. In a chat,
**More → Quick commands** shows them as buttons. Tapping one runs it in the chat's project folder and shows the output.
No agent is involved and no approval is needed, because only the owner can define the list.

## Why

Many "approve this command" moments are routine checks. A fixed, owner-defined list gives the convenience without
letting an agent (or a prompt injection) run arbitrary commands.

## Out of scope

Arguments typed on the phone, interactive commands, streaming output (we show it when the command finishes).

## Read first

- `agents_dialpad/config.py` (`load`), `agents_dialpad/app.py`, `agents_dialpad/runs.py` (`Run.kill`)
- `agents_dialpad/doctor.py` (`run_checks`)
- `agents_dialpad/static/app.js`: `buildPane()` menu, `openSheet()`

## Config format

```json
"quick_commands": {
  "*":      [ { "label": "Git status", "run": ["git", "status", "--short"] } ],
  "my-app": [ { "label": "Run tests", "run": ["npm", "test"], "timeout": 300 } ]
}
```

- `"*"` applies to every project; project-specific entries come after the global ones.
- `run` is a list of strings (program first). Never a single string; there is no shell.
- `label`: 1–40 characters. `timeout`: seconds, 1–1800, default 120.

## Steps

### 1. Shared process helper `agents_dialpad/proc.py`

Move the body of `Run.kill()` into `def kill_tree(pid: int) -> None` (Windows: `taskkill /PID <pid> /T /F`; elsewhere
`os.kill(pid, SIGTERM)`, ignore `ProcessLookupError`). `Run.kill()` then calls `kill_tree(proc.pid)` if the process
is still running. Existing tests must keep passing.

### 2. New module `agents_dialpad/quick.py`

```python
MAX_OUTPUT = 50_000

def normalize(raw) -> tuple[dict[str, list[dict]], list[str]]:
    """Validate config["quick_commands"]. Returns (clean mapping, list of human-readable problems). Never raises."""

def commands_for(mapping: dict, project: str) -> list[dict]:
    """Global ('*') entries first, then the project's. Each item: {"index", "label", "run", "timeout"}."""

async def run(argv: list[str], cwd: str, timeout: int) -> dict:
    """Returns {"exit_code", "timed_out", "output", "truncated", "duration_ms"}."""
```

`run()` details:
1. `exe = shutil.which(argv[0])`; if `None` → raise `FileNotFoundError(argv[0])` (the route turns it into a 400
   `"'<name>' was not found on this computer's PATH"`). `shutil.which` also finds `npm.cmd` on Windows.
2. `asyncio.create_subprocess_exec(exe, *argv[1:], cwd=cwd, stdin=DEVNULL, stdout=PIPE, stderr=STDOUT)`.
3. `await asyncio.wait_for(proc.communicate(), timeout)`. On `TimeoutError`: `kill_tree(proc.pid)`, then
   `await asyncio.wait_for(proc.communicate(), 5)` (ignore a second timeout), `timed_out=True`, `exit_code=None`.
4. Decode UTF-8 with `errors="replace"`. If longer than `MAX_OUTPUT`, keep the **end** and prefix
   `"… output truncated, showing the last 50,000 characters\n"`; `truncated=True`.

### 3. Config

In `config.load()`: `cfg["quick_commands"], cfg["_quick_problems"] = quick.normalize(cfg.get("quick_commands"))`.
(Import inside the function to avoid a cycle if needed.)

### 4. API (`app.py`)

- `GET /api/projects/{project}/commands` → `[{"index", "label"}]` (404 if the project is not in `cfg["projects"]`).
- `POST /api/projects/{project}/commands/{index}` → runs it. 404 unknown project or index.
  One command at a time per project: keep `locks: dict[str, asyncio.Lock]`; if locked → 409 `"Another quick command is still running in this project"`.
- Never accept anything else from the client (no argv, no cwd, no env).

### 5. Doctor

For each item in `cfg["_quick_problems"]` add a `warn` check `"Quick commands"` with the problem text.
For each command whose program is not found by `shutil.which`, add a `warn` naming it.

### 6. UI

1. Chat "More" menu: add **Quick commands** (icon `term`) after Export, only if `GET /projects/<p>/commands` returns
   at least one item (fetch once when the chat opens; cache per project in `state.quick`).
2. Sheet: title "Quick commands", lede "Runs in <project>. Output appears below.", then one full-width
   `btn secondary` per command. While running: that button gets `aria-busy="true"`, the others are disabled.
3. Result area under the buttons: a line "Exit code 0 · 1.4s" (or "Timed out after 120s" in `--danger`), then a
   `<pre class="quick-out">` with the escaped output (max-height 50vh, scroll). Add a **Copy output** button.
4. CSS `.quick-out`: monospace 13 px, `--surface-2` background, 12 px padding, `white-space: pre-wrap`, radius `--r-m`.

## Tests

`tests/test_quick.py` (unit):
1. `test_normalize_keeps_valid_entries_and_reports_bad_ones`: string `run`, empty list, label too long, timeout 0 and
   3600 → each reported; valid ones kept.
2. `test_global_commands_come_first`.
3. `test_run_returns_output_and_exit_code`: `[sys.executable, "-c", "print('hi')"]` → output `hi`, exit 0.
4. `test_nonzero_exit_code_is_reported`: `sys.exit(3)` → 3.
5. `test_timeout_kills_the_process`: `time.sleep(30)` with timeout 1 → `timed_out` true, returns in under 10 s.
6. `test_long_output_is_truncated_from_the_start`: print 60,000 characters → `truncated`, ends with the last characters.
7. `test_missing_program_raises_file_not_found`.

`tests/test_integration.py`:
8. `test_quick_commands_list_and_run`: config with `{"*": [{"label": "Hi", "run": [sys.executable, "-c", "print(42)"]}]}` → list, run, output `42`.
9. `test_unknown_project_or_index_is_404`.
10. `test_quick_commands_need_the_token`: 401.

## Manual check

Add `git status` and a long-running command; run them from a phone; try a timeout; check that the UI stays usable at
320 px.

## Docs

README: new section "Quick commands" with the config example and a clear sentence: **these run with your full user
rights, whatever the chat's permission level; only list commands you would run yourself.** SECURITY.md: same sentence.
CHANGELOG (Added). `config.example.json`: one global example (`git status --short`).

## Acceptance checklist

- [ ] Commands come only from config; the client cannot change argv, cwd or env.
- [ ] Timeouts kill the whole process tree (check Task Manager / `ps` during the timeout test manually once).
- [ ] Output is escaped and capped.
- [ ] Works with `npm` on Windows (`.cmd`).

## Pitfalls

- Do not run through `cmd /c` or `sh -c`. If someone needs pipes, they can list a script file as the program.
- `communicate()` after a kill can hang if a grandchild keeps the pipe open; that is why the second `wait_for` has a 5 s limit.
