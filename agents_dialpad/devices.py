"""Per-device tokens and revocation."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path


class Devices:
    """<data>/devices.json: {"devices": [{"id", "name", "token_sha256", "created", "last_seen"}]}"""

    def __init__(self, path: Path):
        self.path = path
        self._last_saved_seen: dict[str, float] = {}
        self._mtime: tuple[int, int] | None = None
        self._load()

    def _file_mtime(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _fresh(self) -> None:
        """Reload when another process (the `device` CLI) changed devices.json, so a revoke applies at once."""
        if self._file_mtime() != self._mtime:
            self._load()

    def _load(self) -> None:
        self._mtime = self._file_mtime()
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict) and isinstance(data.get("devices"), list):
                    self._devices = data["devices"]
                    for d in self._devices:
                        if d.get("last_seen"):
                            self._last_saved_seen[d["id"]] = d["last_seen"]
                    return
            except (OSError, ValueError):
                pass
        self._devices = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"devices": self._devices}, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self._mtime = self._file_mtime()

    def list(self) -> list[dict]:
        self._fresh()
        return [
            {
                "id": d["id"],
                "name": d["name"],
                "created": d["created"],
                "last_seen": d.get("last_seen"),
            }
            for d in self._devices
        ]

    def add(self, name: str) -> tuple[dict, str]:
        self._fresh()
        clean_name = " ".join(name.split())
        if not clean_name or len(clean_name) > 40:
            raise ValueError("Device name must be 1 to 40 characters")
        dev_id = secrets.token_hex(4)
        raw_token = secrets.token_urlsafe(32)
        h = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now = time.time()
        record = {
            "id": dev_id,
            "name": clean_name,
            "token_sha256": h,
            "created": now,
            "last_seen": None,
        }
        self._devices.append(record)
        self._last_saved_seen[dev_id] = now
        self._save()
        user_record = {
            "id": dev_id,
            "name": clean_name,
            "created": now,
            "last_seen": None,
        }
        return user_record, raw_token

    def revoke(self, device_id: str) -> bool:
        self._fresh()
        before = len(self._devices)
        self._devices = [d for d in self._devices if d["id"] != device_id]
        if len(self._devices) != before:
            self._save()
            return True
        return False

    def known(self, device_id: str) -> bool:
        self._fresh()
        return any(d["id"] == device_id for d in self._devices)

    def match(self, token: str) -> str | None:
        self._fresh()
        h = hashlib.sha256(token.encode("utf-8")).hexdigest()
        for d in self._devices:
            if secrets.compare_digest(d["token_sha256"], h):
                return d["id"]
        return None

    def touch(self, device_id: str) -> None:
        self._fresh()
        now = time.time()
        dev = next((d for d in self._devices if d["id"] == device_id), None)
        if not dev:
            return
        dev["last_seen"] = now
        last_saved = self._last_saved_seen.get(device_id, 0.0)
        if now - last_saved >= 300:
            self._last_saved_seen[device_id] = now
            self._save()
