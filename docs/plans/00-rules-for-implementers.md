# Rules for whoever implements a plan (read this first, every time)

These rules apply to **every** task in `docs/plans/`. A task file tells you *what* to build; this file tells you *how to
work in this repo* without breaking it. If a task file and this file disagree, this file wins, and you report the
conflict instead of guessing.

## 1. What the project is

agents-dialpad is a small self-hosted web app. A FastAPI server on the user's computer launches the official agent CLIs
(`claude`, `agy`) in headless mode, streams their output, and serves a mobile PWA so the user can chat with those agents
from a phone. The server listens on `127.0.0.1` and every API call needs a bearer token.

## 2. Repository map

| Path | What it is |
|---|---|
| `agents_dialpad/app.py` | `create_app(cfg, token)` builds the FastAPI app. All HTTP routes live inside it, on an `APIRouter` with prefix `/api` that requires the token. |
| `agents_dialpad/runs.py` | `RunManager` runs one agent turn per chat as a background asyncio task. `Run` holds the events of that turn. `RunManager.start(chat, text)` starts a turn; `_drive()` consumes the provider's events and saves the chat at the end. |
| `agents_dialpad/store.py` | `Store`: one JSON file per chat in `<data>/chats/<id>.json`. `create`, `get`, `save`, `delete`, `exists`, `list`. Chat ids are 32 hex chars (validated). |
| `agents_dialpad/config.py` | Data folder (`config.DATA`), `load()` (returns `(cfg, token)`), `read_raw()` / `save_raw()`, `ensure_data_dir()`, instructions lookup. New config keys get a default here with `cfg.setdefault(...)`. |
| `agents_dialpad/providers/` | One adapter per CLI: `claude.py`, `antigravity.py`. Each has `name`, `label`, `available()`, `models()`, `stream(chat, prompt, cwd, run, instructions)` which yields normalised events. `_cmd.extra_args()` reads `AG_<NAME>_ARGS`. Registry: `providers/__init__.py` (`PROVIDERS`, `PLANNED`). |
| `agents_dialpad/cli.py` | `agents-dialpad` command (argparse). Subcommands: serve, init, project, token, doctor, autostart. `COMMANDS` must list every subcommand. |
| `agents_dialpad/doctor.py` | `Check` dataclass and `run_checks()`. |
| `agents_dialpad/autostart.py` | Windows/macOS/Linux login-start definitions. |
| `agents_dialpad/static/` | The PWA: `index.html`, `app.js` (all UI logic), `style.css`, `markdown.js` (safe renderer), `sw.js` (service worker), `manifest.webmanifest`, icons. No build step. |
| `tests/` | `test_integration.py` (real app + fake CLIs), `test_cli.py`, `test_parsers.py`, `test_config_store.py`, `js/markdown.test.js`, `fake_agents/fake_claude.py`, `fake_agents/fake_agy.py`. |
| `tools/smoke_wheel.py` | Installs the built wheel into a clean venv and runs it. |
| `scripts/` | Extra Windows helpers for a git checkout (launcher, shortcut, stop). |

Normalised event types (what providers yield and the UI renders):
`session {session_id, model}`, `text {text}`, `tool_use {id, name, input}`, `tool_result {id, text, is_error}`,
`usage {info}`, `done {is_error, result, cost_usd, duration_ms, denials, stopped?}`, `error {message}`.
If a task adds an event type, it must say so explicitly, and both the server and `assistantHTML()` in `app.js` handle it.

## 3. Before you start a task

1. Read: this file, the task file, and every file listed under "Read first" in the task.
2. Create a branch from the latest `main`: `git switch -c feat/<task-id>-<short-slug> origin/main`.
3. Run the baseline and make sure it is green **before** changing anything:
   ```bash
   uv sync
   uv run pytest -q
   node --test tests/js/markdown.test.js
   ```
4. Do the "Verify first" section of the task. If what you observe differs from what the task expects, **stop and
   report** what you saw. Do not invent protocol details, file formats or CLI flags.

## 4. Commands you will use

```bash
uv run pytest -q                                   # all Python tests (unit + end-to-end with fake agents)
uv run pytest tests/test_integration.py -q -x      # just the end-to-end tests, stop at first failure
node --test tests/js/markdown.test.js              # Markdown renderer tests
node --check agents_dialpad/static/app.js          # JS syntax check (also markdown.js, sw.js)
uv run python -m compileall -q agents_dialpad      # Python syntax check
uv build && uv run python tools/smoke_wheel.py "dist/*.whl"   # only when you add files the wheel must contain
uv run agents-dialpad --data-dir <scratch-folder> serve --port 8790   # run a throwaway copy for manual checks
```

Never run the app against the user's real data folder while developing. Always use `--data-dir <scratch folder>` and a
port other than 8787 (the user's real instance runs on 8787).

## 5. Golden rules (security). Breaking one of these fails the task.

1. **Every new route goes on the `api` router** inside `create_app`, so it requires the token. No unauthenticated
   routes except the static UI.
2. **Never use a shell.** Run programs with `asyncio.create_subprocess_exec(exe, *args)` or `subprocess.run([...])`,
   never `shell=True`, never string-built command lines. Anything from the client that becomes an argument must be
   validated first (see `MODEL_RE` in `app.py`).
3. **Paths from the client are never trusted.** Resolve them (`Path(root, rel).resolve()`), then check the result is
   inside the allowed root (`resolved.is_relative_to(root.resolve())`). Reject absolute paths and `..`.
4. **Everything has a limit:** request body size, output size, subprocess timeout, number of items returned.
5. **Never print or log the access token** (or device tokens). Only `agents-dialpad token` prints it, and only to a terminal.
6. **Full access stays opt-in** (`allow_full_access`). New features must not offer a way around the permission level.
7. **Escape everything in the UI.** Use `esc()` for any text from the server. Only agent reply text goes through
   `Markdown.render()`. Never put server text into `innerHTML` unescaped. Never load remote images.
8. **Privacy:** nothing leaves the computer except what the user explicitly enables (for example push notifications,
   whose text is generic by default).
9. **Defaults are safe:** new features that run commands, delete files or send data are off or confirm-before-acting.

## 6. Code conventions

**Python**
- `from __future__ import annotations`, type hints on public functions, small functions with docstrings.
- Errors to the client: `raise HTTPException(<code>, "<sentence the user can act on>")`. Use 400 bad input,
  404 not found, 409 conflict (for example, a run is active), 413 too large, 415 bad file type, 501 optional feature not installed.
- New config key: add `cfg.setdefault("<key>", <default>)` in `config.load()`, a row in the README configuration table,
  and the key in `config.example.json`.
- New dependency: add it to `pyproject.toml`, run `uv lock`, and say why in the PR. Prefer the standard library.
  Heavy or optional dependencies go in `[project.optional-dependencies]` and are imported lazily.

**JavaScript (`app.js`)**: no frameworks, no build step. Reuse these helpers instead of writing new ones:
- `api(path, opts)` / `getJSON(path, opts)`: calls `/api` + path with the token. `opts.body` must already be a JSON string.
- `handleErr(e)`: shows the error (or the login screen on a bad token).
- `toast(msg)`: short message at the bottom.
- `openSheet(html, label)`: returns a `<dialog>` (bottom sheet on phones, centred dialog on wide screens). It removes itself when closed.
- `confirmSheet({title, body, confirm, danger})`: returns a Promise of true/false. Use it before anything destructive.
- `openMenu(anchor, items)`: dropdown menu. `items` are `{icon, label, danger?, run}`.
- `icon(name)`: inline SVG from the `ICON` map. To add an icon, add a 24x24, 1.75-stroke, round-cap path to `ICON`
  (same style as the existing ones). No emoji anywhere in the UI.
- `esc(text)`: HTML-escape. `Markdown.render(text)`: only for agent reply text.
- State: `state` (chat list, info, drafts) and `cur` (the open chat: `{chat, live, ctrl, gen}`).

**CSS**: only use the colour tokens in `:root` (and add both light and dark values for new ones). Touch targets at least
44x44 px. Every interactive element needs hover (inside `@media (hover: hover)`), `:active`, `:focus-visible` and
disabled styles. Animations under 200 ms and disabled under `prefers-reduced-motion`. Sentence case for all labels.

**UI checks for any visible change**: try widths 320, 375, 768 and 1280 px, light and dark. No horizontal scrolling of
the page, nothing cut off, every icon-only button has `aria-label`.

## 7. Tests

- Every task adds tests. Put API behaviour in `tests/test_integration.py` style tests (use the `env` fixture there:
  `client, h = env(**config_overrides)`; `new_chat()`, `turn()`, `wait_until_idle()` helpers).
- **Never call the real `claude`, `agy`, `codex`, `git` remote, Tailscale or the internet from tests.** Extend the fake
  CLIs in `tests/fake_agents/` instead. Local `git` on a temporary repo is fine.
- Tests must pass on Windows, macOS and Linux (CI runs all three). Use `pathlib`, `sys.executable`, and `tmp_path`.
- A test name says the behaviour: `test_revoked_device_token_is_rejected`, not `test_devices_2`.

## 8. Windows pitfalls this project has already hit

- PowerShell 5.1 `Set-Content -Encoding utf8` writes a BOM. `config.read_raw()` tolerates it; any new JSON reader must
  read with `encoding="utf-8-sig"`.
- PowerShell variable names are case-insensitive: `$action` and a parameter `-Action` are the same variable.
- `pythonw.exe` has no stdout/stderr. Code that runs in the background service must not assume they exist (see `cli.ensure_stdio()`).
- npm-style tools are `.cmd` files on Windows. Resolve executables with `shutil.which(name)` before running them.
- The command line is limited to about 32,000 characters. Never put large text in arguments; use stdin or a file.
- Do not use uvicorn `reload=True`: it breaks subprocesses on Windows.
- To find "is the server up", connect to the port (see `cli.port_open`). `Get-NetTCPConnection` is unreliable.
- Never kill processes by a guessed PID. Match the exact command line, and never act on PID 0 or 4.

## 9. Docs to update in the same PR

- `README.md`: the user-facing behaviour (and the configuration table if you added keys).
- `CHANGELOG.md`: a line under `## [Unreleased]` (Added / Changed / Fixed).
- `config.example.json`: new keys with their default.
- `SECURITY.md`: if the feature changes what can reach the computer or what data leaves it.

## 10. Git and pull requests

- One task per branch and per PR. Do not mix tasks.
- Commit messages: `feat: <what the user gets>` / `fix: ...` / `docs: ...`, then a short body.
- The PR description says: what changed, how you tested (OS, commands), what you could not test, and screenshots at
  375 px and 1280 px for UI changes.
- CI must be green on all four jobs before asking for a merge. Do not merge your own PR unless the owner said so.

## 11. Definition of done (copy into your PR and tick it)

- [ ] Every step in the task file is done, or the PR explains why not.
- [ ] New tests added; `uv run pytest -q` and the JS tests pass locally.
- [ ] Golden rules (section 5) checked one by one.
- [ ] UI checked at 320 / 375 / 768 / 1280 px, light and dark (if the UI changed).
- [ ] README, CHANGELOG and config.example.json updated.
- [ ] No token, personal path, hostname or email in code, tests, docs or screenshots.

## 12. When you are stuck

Stop and write down: what you tried, the exact error text, and what you expected. Do not delete tests to make CI
green, do not weaken a golden rule, and do not guess an external protocol. Ask the owner.
