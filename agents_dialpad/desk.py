"""Claude Code desktop sessions integration."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

MAX_FILES = 500          # newest session files scanned
MAX_LINES = 200          # lines read per file while looking for cwd and the first user message
PREVIEW = 120            # characters
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def claude_projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except Exception:
        return False


def _first_user_text(record: dict) -> str | None:
    """Plain text of a user message; None for tool results, sidechains, or text starting with '<' (command/system markup)."""
    if record.get("type") != "user" or record.get("isSidechain"):
        return None
    msg = record.get("message")
    text = None
    if isinstance(msg, str):
        text = msg
    else:
        content = msg.get("content") if isinstance(msg, dict) else (msg if isinstance(msg, list) else None)
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text")
                    if text:
                        break

    if not text or not isinstance(text, str):
        return None
    clean = " ".join(text.split())
    if clean.startswith("<") or not clean:
        return None
    return clean[:PREVIEW]


def list_sessions(project_path: str, exclude_ids: set[str], limit: int = 20) -> list[dict]:
    """[{"id", "updated" (epoch seconds, file mtime), "preview"}], newest first.
    Scan the newest MAX_FILES *.jsonl files under claude_projects_dir()/*/. For each, read up to MAX_LINES lines:
    skip lines that are not JSON; the first record with "cwd" decides the project (skip the file if it does not match);
    the first user text becomes the preview. Skip files with no user text, files whose stem is not a UUID, and ids in exclude_ids."""
    p_dir = claude_projects_dir()
    if not p_dir.exists():
        return []

    candidates: list[tuple[float, Path]] = []
    try:
        for p in p_dir.glob("*/*.jsonl"):
            if not UUID_RE.match(p.stem) or p.stem in exclude_ids:
                continue
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                pass
    except OSError:
        return []

    candidates.sort(key=lambda x: x[0], reverse=True)
    candidates = candidates[:MAX_FILES]

    results: list[dict] = []
    for mtime, path in candidates:
        cwd = None
        preview = None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for _ in range(MAX_LINES):
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if cwd is None and "cwd" in rec and isinstance(rec["cwd"], str):
                        cwd = rec["cwd"]
                        if not _same_path(cwd, project_path):
                            break
                    if preview is None:
                        t = _first_user_text(rec)
                        if t:
                            preview = t
                    if cwd is not None and preview is not None:
                        break
        except OSError:
            continue

        if cwd and _same_path(cwd, project_path) and preview:
            results.append({"id": path.stem, "updated": mtime, "preview": preview})
            if len(results) >= limit:
                break

    return results


def session_belongs_to(project_path: str, session_id: str) -> bool:
    """True if a file named <session_id>.jsonl exists under claude_projects_dir() and its first cwd matches project_path."""
    if not UUID_RE.match(session_id):
        return False
    p_dir = claude_projects_dir()
    if not p_dir.exists():
        return False
    try:
        for path in p_dir.glob(f"*/{session_id}.jsonl"):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for _ in range(MAX_LINES):
                        line = f.readline()
                        if not line:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(rec, dict) and "cwd" in rec and isinstance(rec["cwd"], str):
                            return _same_path(rec["cwd"], project_path)
            except OSError:
                pass
    except OSError:
        return False
    return False
