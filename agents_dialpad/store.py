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

    def create(self, provider: str, project: str, mode: str, model: str = "") -> dict:
        now = time.time()
        chat = {
            "id": uuid.uuid4().hex,
            "title": "New chat",
            "provider": provider,
            "project": project,
            "mode": mode,
            "model": model,  # "" = the CLI's default
            "session_id": None,
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
            out.append({k: c.get(k) for k in ("id", "title", "provider", "project", "mode", "updated")})
        out.sort(key=lambda c: c["updated"] or 0, reverse=True)
        return out
