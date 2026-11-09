"""Tiny JSON-file chat store (one file per chat)."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

ID_RE = re.compile(r"^[0-9a-f]{32}$")


class Store:
    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, chat_id: str) -> Path:
        if not ID_RE.match(chat_id):
            raise KeyError(chat_id)
        return self.dir / f"{chat_id}.json"

    def create(self, provider: str, project: str, mode: str, model: str = "", group: str | None = None) -> dict:
        now = time.time()
        chat = {
            "id": uuid.uuid4().hex,
            "title": "New chat",
            "provider": provider,
            "project": project,
            "mode": mode,
            "model": model,  # "" = the CLI's default
            "group": group,
            "session_id": None,
            "pinned": False,
            "created": now,
            "updated": now,
            "messages": [],
        }
        self.save(chat)
        return chat

    def get(self, chat_id: str) -> dict:
        path = self._path(chat_id)
        if not path.exists():
            raise KeyError(chat_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, chat: dict) -> None:
        path = self._path(chat["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(chat), encoding="utf-8")
        os.replace(tmp, path)

    def exists(self, chat_id: str) -> bool:
        try:
            return self._path(chat_id).exists()
        except KeyError:
            return False

    def delete(self, chat_id: str) -> None:
        path = self._path(chat_id)
        if path.exists():
            path.unlink()

    def list(self) -> list[dict]:
        out = []
        for p in self.dir.glob("*.json"):
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            item = {k: c.get(k) for k in ("id", "title", "provider", "project", "mode", "updated", "group")}
            item["pinned"] = bool(c.get("pinned"))
            out.append(item)
        out.sort(key=lambda c: (not c["pinned"], -(c["updated"] or 0)))
        return out

    def search(self, q: str, limit: int = 50) -> list[dict]:
        """Case-insensitive substring match on title, user messages and assistant text. Adds a short 'snippet'."""
        out = []
        q_lower = q.lower()
        if not q_lower:
            return self.list()[:limit]

        for p in self.dir.glob("*.json"):
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue

            texts: list[str] = []
            if c.get("title"):
                texts.append(c["title"])
            for m in c.get("messages", []):
                if m.get("role") == "user" and m.get("text"):
                    texts.append(m["text"])
                elif m.get("role") == "assistant":
                    for ev in m.get("events", []):
                        if ev.get("type") == "text" and ev.get("text"):
                            texts.append(ev["text"])

            match_text = None
            pos = -1
            for t in texts:
                idx = t.lower().find(q_lower)
                if idx != -1:
                    match_text = t
                    pos = idx
                    break

            if match_text is None:
                continue

            start = max(0, pos - 40)
            end = min(len(match_text), pos + len(q) + 60)
            raw_snippet = match_text[start:end]
            collapsed = " ".join(raw_snippet.split())
            if start > 0:
                collapsed = "…" + collapsed
            if end < len(match_text):
                collapsed = collapsed + "…"

            item = {k: c.get(k) for k in ("id", "title", "provider", "project", "mode", "updated", "group")}
            item["pinned"] = bool(c.get("pinned"))
            item["snippet"] = collapsed
            out.append(item)

        out.sort(key=lambda c: (not c["pinned"], -(c["updated"] or 0)))
        return out[:limit]
