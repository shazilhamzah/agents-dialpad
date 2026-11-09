"""App lock: WebAuthn passkeys (Face ID, Touch ID, fingerprint) for device locking."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

try:
    import webauthn
    from webauthn import (
        generate_authentication_options,
        generate_registration_options,
        options_to_json,
        verify_authentication_response,
        verify_registration_response,
    )
    from webauthn.helpers.structs import (
        AuthenticatorAttachment,
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )
    WEBAUTHN_AVAILABLE = True
except ImportError:
    webauthn = None  # type: ignore
    WEBAUTHN_AVAILABLE = False

log = logging.getLogger("agents-dialpad.applock")


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def b64url_decode(s: str) -> bytes:
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    return base64.urlsafe_b64decode(s)


class LockStore:
    """<data>/lock.json: atomic storage of registered passkeys per identity."""

    def __init__(self, path: Path):
        self.path = path
        self._mtime: float | None = None
        self._creds: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                mt = self.path.stat().st_mtime
                if mt != self._mtime:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and isinstance(raw.get("credentials"), list):
                        self._creds = raw["credentials"]
                        self._mtime = mt
                        return
            except (OSError, ValueError):
                pass
        else:
            self._creds = []
            self._mtime = None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"credentials": self._creds}, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime = None

    def list(self, who: str | None = None) -> list[dict]:
        self._load()
        if who is None:
            return list(self._creds)
        return [c for c in self._creds if c.get("who") == who]

    def has_lock(self, who: str) -> bool:
        self._load()
        return any(c.get("who") == who for c in self._creds)

    def get_credential(self, who: str, credential_id: str) -> dict | None:
        self._load()
        for c in self._creds:
            if c.get("who") == who and c.get("credential_id") == credential_id:
                return c
        return None

    def add(self, who: str, cred: dict) -> None:
        self._load()
        cid = cred.get("credential_id")
        self._creds = [c for c in self._creds if c.get("credential_id") != cid]
        entry = {
            "who": who,
            "credential_id": cid,
            "public_key": cred.get("public_key"),
            "sign_count": int(cred.get("sign_count", 0)),
            "rp_id": cred.get("rp_id", ""),
            "name": cred.get("name", "Passkey"),
            "created": cred.get("created", time.time()),
        }
        self._creds.append(entry)
        self._save()

    def remove(self, who: str, credential_id: str) -> bool:
        self._load()
        before = len(self._creds)
        self._creds = [c for c in self._creds if not (c.get("who") == who and c.get("credential_id") == credential_id)]
        if len(self._creds) != before:
            self._save()
            return True
        return False

    def reset(self, who: str | None = None) -> int:
        self._load()
        if who is None:
            count = len(self._creds)
            self._creds = []
            self._save()
            return count
        before = len(self._creds)
        self._creds = [c for c in self._creds if c.get("who") != who]
        diff = before - len(self._creds)
        if diff > 0:
            self._save()
        return diff

    def update_sign_count(self, credential_id: str, new_sign_count: int) -> None:
        self._load()
        for c in self._creds:
            if c.get("credential_id") == credential_id:
                c["sign_count"] = new_sign_count
                self._save()
                return


class Sessions:
    """In-memory unlock sessions validated against idle expiration."""

    def __init__(self, idle_seconds: float = 300.0):
        self.idle_seconds = idle_seconds
        # token_hash -> {"who": who, "last_used": float}
        self._sessions: dict[str, dict] = {}

    def create(self, who: str) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        th = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        self._sessions[th] = {"who": who, "last_used": now}
        return token, int(self.idle_seconds)

    def check(self, token: str, who: str) -> bool:
        if not token:
            return False
        th = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        entry = self._sessions.get(th)
        if not entry:
            return False
        if not secrets.compare_digest(entry["who"], who):
            return False
        if now - entry["last_used"] > self.idle_seconds:
            self._sessions.pop(th, None)
            return False
        entry["last_used"] = now
        return True

    def drop_token(self, token: str) -> None:
        th = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._sessions.pop(th, None)

    def drop_all(self, who: str | None = None) -> None:
        if who is None:
            self._sessions.clear()
            return
        self._sessions = {k: v for k, v in self._sessions.items() if v.get("who") != who}


class RateLimiter:
    """Rate limit unlock attempts: at most 10 failed attempts per 10 minutes per identity."""

    def __init__(self, max_fails: int = 10, window_seconds: float = 600.0):
        self.max_fails = max_fails
        self.window_seconds = window_seconds
        self._fails: dict[str, list[float]] = {}

    def is_blocked(self, who: str) -> bool:
        now = time.time()
        times = [t for t in self._fails.get(who, []) if now - t < self.window_seconds]
        self._fails[who] = times
        return len(times) >= self.max_fails

    def record_fail(self, who: str) -> None:
        now = time.time()
        times = [t for t in self._fails.get(who, []) if now - t < self.window_seconds]
        times.append(now)
        self._fails[who] = times

    def reset(self, who: str) -> None:
        self._fails.pop(who, None)


def get_allowed_origins(port: int, tailscale_url: str | None = None) -> list[str]:
    """Origins a WebAuthn ceremony may come from: loopback on our port, plus the Tailscale HTTPS URL.

    Never built from the request's Host header, which a client controls.
    """
    origins = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
    if tailscale_url:
        origins.append(tailscale_url.rstrip("/"))
    return origins
