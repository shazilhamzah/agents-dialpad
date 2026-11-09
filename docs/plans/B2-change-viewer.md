# B2. Change viewer: see and revert what the agent changed

- **Size:** M
- **Needs first:** A3
- **Branch:** `feat/b2-changes`
- **PR title:** `feat: review and revert file changes from the phone`

## Goal

In a chat, **More → Changes** lists the files that differ from the last commit in that chat's project (git status).
Tapping a file shows its diff with added and removed lines coloured. A **Revert this file** button (with confirmation)
restores a tracked file to the last commit.

## Why

After "Can edit files" or "Full access" replies, the user needs to see what actually changed before trusting it.
Reviewing a diff on a phone is the missing piece.

## Out of scope

Committing, staging, branches, untracked-file deletion, binary diffs, side-by-side diffs.

## Read first

- `agents_dialpad/app.py`, `agents_dialpad/runs.py` (`Run`, `RunManager.start`, `active`)
- `agents_dialpad/static/app.js` (`buildPane` menu, `openSheet`, `confirmSheet`), `agents_dialpad/static/style.css` tokens

## Verify first

1. `git --version` is 2.23 or newer on your machine (needed for `git restore`).
2. In a scratch repo, check these commands behave as described:
   - `git -C <root> status --porcelain=v1 -z --untracked-files=all` prints NUL-separated entries `XY<space>path`; for
     renames (`R` in X or Y) the **next** NUL-separated item is the original path.
   - `git -C <root> diff HEAD --no-color --no-ext-diff -- <path>` prints a unified diff for tracked changes.
   - `git -C <root> cat-file -e HEAD:<path>` exits 0 only if the path exists in the last commit.

## Steps

### 1. Track the project of each run

In `runs.py`, `Run.__init__` gets `project: str = ""`; `RunManager.start` passes `chat["project"]`. Add
`def active_in_project(self, project) -> bool` (any active run whose `project` matches).

### 2. New module `agents_dialpad/gitview.py`

```python
MAX_DIFF = 300_000          # characters
MAX_UNTRACKED = 512_000     # bytes read for an untracked file preview
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}

def safe_path(root: Path, rel: str) -> Path:
    """Reject absolute paths, empty paths, '..' segments, NUL; resolve and require it to stay inside root. ValueError otherwise."""

async def git(root: Path, *args: str, timeout: float = 20) -> tuple[int, str]:
    """Run `git -c core.quotepath=off -C <root> <args>` without a shell; decode UTF-8 (replace). Kill on timeout and raise TimeoutError."""

async def status(root: Path) -> dict:
    """{"is_repo": bool, "branch": str|None, "files": [{"path", "orig_path"?, "code": "M|A|D|R|C|U|??", "label": "modified|added|deleted|renamed|copied|conflict|untracked"}]}
    Not a repo (rev-parse --is-inside-work-tree fails) -> {"is_repo": False, "files": []}. Cap files at 500."""

async def diff(root: Path, rel: str) -> dict:
    """{"path", "kind": "text|binary|too_large|untracked", "diff": str, "truncated": bool}
    Tracked: git diff HEAD -- rel. Untracked: read the file (max MAX_UNTRACKED bytes); a NUL byte in the first 8 KB means
    binary; otherwise build a synthetic diff where every line starts with '+'. Truncate the diff to MAX_DIFF."""

async def revert(root: Path, rel: str) -> None:
    """Only for paths that exist in HEAD (cat-file -e). Runs: git restore --source=HEAD --staged --worktree -- rel.
    Raise LookupError for files not in HEAD (new files)."""
```

Code letters: take the porcelain `XY`; use Y if it is not a space, otherwise X; `??` stays `??`; `U` in either is a conflict.
A repository with no commits: treat every file as untracked-style (`diff` builds the synthetic diff; `revert` raises `LookupError`).

### 3. Routes (`app.py`)

All take the project **name** (must be in `cfg["projects"]`, else 404) and resolve its folder from config:

| Route | Result |
|---|---|
| `GET /api/projects/{project}/changes` | `status()` result |
| `GET /api/projects/{project}/changes/diff?path=<rel>` | `diff()` result; 400 if `safe_path` fails |
| `POST /api/projects/{project}/changes/revert` body `{"path": "<rel>"}` | 200; 400 bad path; 409 `"An agent is working in this project; wait for it to finish"` if `runs.active_in_project`; 409 `"This file is new, so there is nothing to revert to"` on `LookupError` |

Timeouts from `git()` → 504 `"git took too long"`. Git missing (`FileNotFoundError`) → 501 `"git is not installed on this computer"`.

### 4. UI

1. Chat More menu: **Changes** (icon `diff`: `<path d="M12 3v14M5 10h14M5 21h14"/>`), placed right after Export.
2. Sheet (wider on desktop: add class `wide` to the dialog; CSS `dialog.sheet.wide { width: min(94vw, 60rem); }`):
   - Header line: branch name and "N changed files", or "This folder is not a git repository" / "No changes since the last commit".
   - File list: each row is a `<button>` (44 px min height) with a status badge and the path in monospace; long paths
     are truncated **in the middle** (keep the file name visible: show `…/` + last 2 segments when longer than 48 characters).
     The badge shows the letter and has `aria-label` with the label (for example "modified").
   - Tapping a row replaces the list with the diff view: a back button ("All changes"), the path, the diff, and for
     tracked files a **Revert this file** danger button → `confirmSheet({title: 'Revert this file?', body: 'Your
     uncommitted changes to <path> will be lost. This can\'t be undone.', confirm: 'Revert', danger: true})` → POST →
     toast "Reverted" → back to the refreshed list.
3. Diff rendering: split on `\n`; for each line create `<div class="dl add|del|hunk|meta|ctx">` with **escaped** text.
   `+` (not `+++`) → add, `-` (not `---`) → del, `@@` → hunk, `diff `/`index `/`---`/`+++` → meta, else ctx.
   Container: monospace 12.5 px, `overflow-x: auto`, lines `white-space: pre`. Show "Binary file, not shown" /
   "Too large to show" for those kinds, and "Showing the first part only" when truncated.
4. CSS tokens (add to both light and dark `:root` blocks): `--add-bg` (light `#e6f4ea`, dark `#12331f`), `--del-bg`
   (light `#fdecec`, dark `#3a1517`). Text colour stays `--text` so contrast is unchanged. Add `--add-mark` / `--del-mark`
   for a 3 px left border (`--ok` / `--danger`) so colour is not the only signal.

## Tests

`tests/test_gitview.py` (uses a real local git repo in `tmp_path`; set `user.name`/`user.email` with `-c` on commit):
1. `test_not_a_repo_is_reported`.
2. `test_status_lists_modified_added_deleted_and_untracked`.
3. `test_renames_report_both_paths` (`git mv`, then status).
4. `test_diff_of_a_modified_file_has_added_and_removed_lines`.
5. `test_untracked_text_file_becomes_an_all_added_diff` and `test_binary_untracked_file_is_not_shown`.
6. `test_diff_is_truncated_when_huge`.
7. `test_revert_restores_a_tracked_file` and `test_revert_refuses_new_files`.
8. `test_paths_outside_the_project_are_rejected`: `../x`, `/etc/passwd`, `C:\\x`, `a/../../x`, `""`, `"a\0b"`.

`tests/test_integration.py`:
9. `test_changes_routes_need_the_token_and_a_known_project`.
10. `test_revert_is_refused_while_an_agent_runs_in_that_project` (send `"SLOW"`, POST revert → 409, then stop).

## Manual check

Let an agent edit a real file in a test repository; open Changes on a phone; read the diff; revert; confirm with
`git status` on the computer. Check 375 px (long paths, wide diff scrolls sideways inside its box only) and 1280 px.

## Docs

README: "Reviewing changes" section. CHANGELOG (Added).

## Acceptance checklist

- [ ] No route accepts a path that escapes the project folder (tests 8).
- [ ] Diff text is escaped; a file containing `<script>` shows as text.
- [ ] Revert asks first, only works on tracked files, and is blocked while an agent works in that project.
- [ ] Colour is not the only signal for added/removed lines.

## Pitfalls

- Always pass `--` before paths so a file named `-rf` is not read as an option.
- Do not run `git diff` without `--no-ext-diff`: users can configure external diff tools that would launch programs.
- `core.quotepath=off` keeps non-ASCII file names readable.
