"""Web Push notifications for finished turns."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


class PushUnavailable(Exception):
    """pywebpush is not installed."""


def validate_subscription(sub: dict) -> dict:
    """Validate subscription shape.

    endpoint must be an https URL (max 1000 chars); keys.p256dh and keys.auth
    non-empty strings (max 200). Raise ValueError otherwise.
    """
    if not isinstance(sub, dict):
        raise ValueError("Subscription must be an object")
    endpoint = sub.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 1000:
        raise ValueError("Invalid endpoint URL")
    keys = sub.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("Missing keys object")
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not isinstance(p256dh, str) or not (1 <= len(p256dh) <= 200):
        raise ValueError("Invalid p256dh key")
    if not isinstance(auth, str) or not (1 <= len(auth) <= 200):
        raise ValueError("Invalid auth key")
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


class Subscriptions:
    """<data>/push.json: {"subscriptions": [{"endpoint", "keys": {"p256dh", "auth"}, "label", "created", "device"?}]}

    `keep(sub)` hides subscriptions that should no longer get pushes (a revoked device's phone)."""

    def __init__(self, path: Path, keep=None):
        self.path = path
        self.keep = keep
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("subscriptions"), list):
                    self._subs = data["subscriptions"]
                    return
            except (OSError, ValueError):
                pass
        self._subs = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"subscriptions": self._subs}, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def all(self) -> list[dict]:
        return [s for s in self._subs if self.keep is None or self.keep(s)]

    def add(self, sub: dict, label: str, device: str | None = None) -> None:
        clean = validate_subscription(sub)
        entry = {
            "endpoint": clean["endpoint"],
            "keys": clean["keys"],
            "label": str(label)[:40],
            "created": time.time(),
        }
        if device:
            entry["device"] = device
        self._subs = [s for s in self._subs if s.get("endpoint") != clean["endpoint"]]
        self._subs.append(entry)
        self._save()

    def remove_device(self, device_id: str) -> None:
        before_len = len(self._subs)
        self._subs = [s for s in self._subs if s.get("device") != device_id]
        if len(self._subs) != before_len:
            self._save()

    def remove(self, endpoint: str) -> bool:
        before_len = len(self._subs)
        self._subs = [s for s in self._subs if s.get("endpoint") != endpoint]
        if len(self._subs) != before_len:
            self._save()
            return True
        return False


def vapid_public_key(data_dir: Path) -> str:
    """Create <data>/vapid_private.pem on first use; return application server key (base64url, uncompressed point)."""
    try:
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid
        from py_vapid.utils import b64urlencode
    except ImportError as e:
        raise PushUnavailable("pywebpush is not installed") from e

    data_dir.mkdir(parents=True, exist_ok=True)
    pem_path = data_dir / "vapid_private.pem"
    if not pem_path.exists():
        v = Vapid()
        v.generate_keys()
        v.save_key(str(pem_path))
    else:
        v = Vapid.from_file(str(pem_path))

    raw_bytes = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64urlencode(raw_bytes)


def build_payload(chat: dict, done: dict | None, show_titles: bool) -> dict:
    """Build push notification payload."""
    if done and done.get("is_error"):
        body = "A reply failed"
    elif done and done.get("denials"):
        body = "A reply finished, but a command was blocked"
    else:
        body = "Your reply is ready"

    if show_titles:
        title = (chat.get("title") or "").strip()
        if title:
            body = f"{body}: {title[:60]}"

    chat_id = chat.get("id", "")
    return {
        "title": "agents-dialpad",
        "body": body,
        "tag": chat_id,
        "url": "/#/c/" + chat_id,
    }


def send_all(subs: Subscriptions, payload: dict, data_dir: Path, contact: str) -> int:
    """Blocking. Send to every subscription; remove those that answer 404 or 410. Return how many succeeded."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError as e:
        raise PushUnavailable("pywebpush is not installed") from e

    pem_path = data_dir / "vapid_private.pem"
    if not pem_path.exists():
        vapid_public_key(data_dir)

    sent = 0
    for sub in subs.all():
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps(payload),
                vapid_private_key=str(pem_path),
                vapid_claims={"sub": contact},
                ttl=3600,
            )
            sent += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                subs.remove(sub["endpoint"])
            else:
                status = e.response.status_code if e.response is not None else "no response"
                print(f"push: failed to send ({status})")
        except Exception as e:
            print(f"push: failed to send ({type(e).__name__}: {e})")
    return sent
