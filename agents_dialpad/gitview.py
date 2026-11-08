"""Git operations for reviewing and reverting project changes."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .proc import kill_tree

MAX_DIFF = 300_000          # characters
MAX_UNTRACKED = 512_000     # bytes read for an untracked file preview
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}


def safe_path(root: Path, rel: str) -> Path:
    """Reject absolute paths, empty paths, '..' segments, NUL; resolve and require it to stay inside root. ValueError otherwise."""
    if not isinstance(rel, str) or not rel or "\0" in rel:
        raise ValueError("Invalid path")
    p = Path(rel)
    if p.is_absolute() or rel.startswith(("/", "\\")) or (len(rel) >= 2 and rel[1] == ":"):
        raise ValueError("Absolute path not allowed")
    parts = rel.replace("\\", "/").split("/")
    if any(part in ("..", ".", "") for part in parts):
        raise ValueError("Invalid path segment")
    resolved_root = root.resolve()
    target = (resolved_root / rel).resolve()
    try:
        if not target.is_relative_to(resolved_root):
            raise ValueError("Path escapes root")
    except (ValueError, AttributeError):
        raise ValueError("Path escapes root")
    if target == resolved_root:
        raise ValueError("Target cannot be root directory")
    return target


async def git(root: Path, *args: str, timeout: float = 20) -> tuple[int, str]:
    """Run `git -c core.quotepath=off -C <root> <args>` without a shell; decode UTF-8 (replace). Kill on timeout and raise TimeoutError."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "core.quotepath=off",
        "-C",
        str(root),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=GIT_ENV,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        kill_tree(proc.pid)
        raise TimeoutError("git command timed out")
    return proc.returncode, stdout.decode("utf-8", errors="replace")


async def status(root: Path) -> dict:
    """{"is_repo": bool, "branch": str|None, "files": [{"path", "orig_path"?, "code": "M|A|D|R|C|U|??", "label": "modified|added|deleted|renamed|copied|conflict|untracked"}]}
    Not a repo (rev-parse --is-inside-work-tree fails) -> {"is_repo": False, "files": []}. Cap files at 500."""
    code, out = await git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        return {"is_repo": False, "files": []}

    code, out = await git(root, "branch", "--show-current")
    branch = out.strip() or None

    code, out = await git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    items = out.split("\0")
    if items and items[-1] == "":
        items.pop()

    files: list[dict] = []
    idx = 0
    labels = {
        "M": "modified",
        "A": "added",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "U": "conflict",
        "??": "untracked",
    }
    while idx < len(items) and len(files) < 500:
        item = items[idx]
        idx += 1
        if len(item) < 3:
            continue
        xy = item[:2]
        path = item[3:]
        x, y = xy[0], xy[1]
        orig_path = None
        if "R" in (x, y) or "C" in (x, y):
            if idx < len(items):
                orig_path = items[idx]
                idx += 1
        if xy == "??":
            code_letter = "??"
            label = "untracked"
        elif "U" in (x, y):
            code_letter = "U"
            label = "conflict"
        else:
            code_letter = y if y != " " else x
            label = labels.get(code_letter, "modified")
        entry = {"path": path, "code": code_letter, "label": label}
        if orig_path:
            entry["orig_path"] = orig_path
        files.append(entry)

    return {"is_repo": True, "branch": branch, "files": files}


async def diff(root: Path, rel: str) -> dict:
    """{"path", "kind": "text|binary|too_large|untracked", "diff": str, "truncated": bool}
    Tracked: git diff HEAD -- rel. Untracked: read the file (max MAX_UNTRACKED bytes); a NUL byte in the first 8 KB means
    binary; otherwise build a synthetic diff where every line starts with '+'. Truncate the diff to MAX_DIFF."""
    target = safe_path(root, rel)
    rel_git = rel.replace("\\", "/")

    code, out = await git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        raise ValueError("Not a git repository")

    code, _ = await git(root, "rev-parse", "--verify", "HEAD")
    has_head = (code == 0)

    is_untracked = False
    if not has_head:
        is_untracked = True
    else:
        code, status_out = await git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", rel_git)
        if status_out.startswith("??"):
            is_untracked = True

    if is_untracked:
        if not target.exists() or not target.is_file():
            return {"path": rel_git, "kind": "untracked", "diff": "", "truncated": False}
        file_size = target.stat().st_size
        if file_size > MAX_UNTRACKED:
            return {"path": rel_git, "kind": "too_large", "diff": "", "truncated": False}
        with open(target, "rb") as f:
            chunk = f.read(min(file_size, MAX_UNTRACKED))
        if b"\x00" in chunk[:8192]:
            return {"path": rel_git, "kind": "binary", "diff": "", "truncated": False}
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            return {"path": rel_git, "kind": "binary", "diff": "", "truncated": False}
        lines = text.splitlines(keepends=True)
        synthetic = "".join("+" + l for l in lines)
        truncated = False
        if len(synthetic) > MAX_DIFF:
            synthetic = synthetic[:MAX_DIFF]
            truncated = True
        return {"path": rel_git, "kind": "untracked", "diff": synthetic, "truncated": truncated}

    # Tracked: git diff HEAD -- rel
    code, diff_out = await git(root, "diff", "HEAD", "--no-color", "--no-ext-diff", "--", rel_git)
    if "Binary files " in diff_out and " differ" in diff_out:
        return {"path": rel_git, "kind": "binary", "diff": "", "truncated": False}
    truncated = False
    if len(diff_out) > MAX_DIFF:
        diff_out = diff_out[:MAX_DIFF]
        truncated = True
    return {"path": rel_git, "kind": "text", "diff": diff_out, "truncated": truncated}


async def revert(root: Path, rel: str) -> None:
    """Only for paths that exist in HEAD (cat-file -e). Runs: git restore --source=HEAD --staged --worktree -- rel.
    Raise LookupError for files not in HEAD (new files)."""
    safe_path(root, rel)
    rel_git = rel.replace("\\", "/")

    code, out = await git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        raise ValueError("Not a git repository")

    code, _ = await git(root, "cat-file", "-e", f"HEAD:{rel_git}")
    if code != 0:
        raise LookupError("This file is new, so there is nothing to revert to")

    code, err = await git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", rel_git)
    if code != 0:
        raise RuntimeError(f"git restore failed: {err}")
