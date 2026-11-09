# B1. Push notifications

- **Size:** M
- **Needs first:** A2 (sidebar More menu)
- **Branch:** `feat/b1-push`
- **PR title:** `feat: push notifications when a reply is ready`

## Goal

The user turns on **Notifications** from the sidebar More menu. From then on, when a reply finishes, the phone shows a
notification (lock screen included). Tapping it opens that chat. By default the text is generic ("Your reply is
ready"), so no conversation content goes through Apple's or Google's push servers.

## Why

Agents take minutes. Without notifications the user keeps reopening the app to check.

## How Web Push works here (read before coding)

1. The server owns a **VAPID key pair** (stored in the data folder). The public key goes to the browser.
2. The browser's service worker subscribes with that key and gets a **subscription** (an HTTPS endpoint at Apple/Google/
   Mozilla plus two keys). The app sends it to our server, which stores it.
3. To notify, the server encrypts a small JSON payload and POSTs it to that endpoint (library: `pywebpush`). The push
   service wakes the service worker, which calls `showNotification`.
4. **iPhone/iPad:** only works for the app **added to the Home Screen** (iOS/iPadOS 16.4+), opened from its icon, over
   HTTPS (Tailscale Serve is fine). In a normal Safari tab, `PushManager` is missing.
5. The computer needs outbound internet to reach the push service. Nothing needs to reach the computer.

## Read first

- `agents_dialpad/runs.py` (`_drive` `finally:`), `agents_dialpad/app.py`, `agents_dialpad/config.py`
- `agents_dialpad/static/sw.js`, `agents_dialpad/static/app.js` (`sideMenuItems()` from A2, `toast`, `getJSON`)

## Verify first

Install the optional dependency in your dev environment (`uv add --optional push pywebpush`, then
`uv sync --all-extras`) and check these APIs exist with these names (stop and report if not):

```python
from pywebpush import webpush, WebPushException          # webpush(subscription_info=, data=, vapid_private_key=, vapid_claims=, ttl=)
from py_vapid import Vapid                                # Vapid().generate_keys(); .save_key(path); .public_key
from py_vapid.utils import b64urlencode
from cryptography.hazmat.primitives import serialization   # Encoding.X962, PublicFormat.UncompressedPoint
```

## Steps

### 1. Packaging

`pyproject.toml`: `[project.optional-dependencies] push = ["pywebpush>=2"]`. Also add `pywebpush` to the `dev`
dependency group so CI can test it. `uv lock`. Users install with `uv tool install "agents-dialpad[push] @ git+https://github.com/shazilhamzah/agents-dialpad"`.

### 2. Config

`config.load()`: `cfg.setdefault("push_show_titles", False)` and
`cfg.setdefault("push_contact", "mailto:agents-dialpad@example.com")`.

### 3. New module `agents_dialpad/push.py`

```python
class PushUnavailable(Exception): """pywebpush is not installed."""

class Subscriptions:
    """<data>/push.json: {"subscriptions": [{"endpoint", "keys": {"p256dh", "auth"}, "label", "created"}]}"""
    def __init__(self, path: Path): ...
    def all(self) -> list[dict]: ...
    def add(self, sub: dict, label: str) -> None: ...     # replaces an existing entry with the same endpoint
    def remove(self, endpoint: str) -> bool: ...

def validate_subscription(sub) -> dict:
    """endpoint must be an https URL (max 1000 chars); keys.p256dh and keys.auth non-empty strings (max 200). Raise ValueError otherwise."""

def vapid_public_key(data_dir: Path) -> str:
    """Create <data>/vapid_private.pem on first use; return the application server key (base64url, uncompressed point). Raises PushUnavailable."""

def build_payload(chat: dict, done: dict | None, show_titles: bool) -> dict:
    """{"title": "agents-dialpad", "body": ..., "tag": chat["id"], "url": "/#/c/" + chat["id"]}
    body: error -> "A reply failed"; denials -> "A reply finished, but a command was blocked";
    otherwise "Your reply is ready". If show_titles: append ': ' + chat title (max 60 chars)."""

def send_all(subs: Subscriptions, payload: dict, data_dir: Path, contact: str) -> int:
    """Blocking. Send to every subscription; remove those that answer 404 or 410. Return how many succeeded."""
```

In `send_all`, call `webpush(subscription_info=sub, data=json.dumps(payload), vapid_private_key=str(pem_path),
vapid_claims={"sub": contact}, ttl=3600)`. Catch `WebPushException`: if `e.response is not None and
e.response.status_code in (404, 410)` remove the subscription; otherwise print one line with the status (never the
endpoint, it is a secret-ish URL).

### 4. Hook in `runs.py`

`RunManager.__init__(..., on_finish=None)`. At the end of `_drive`'s `finally:` (after `await run.finish()`):

```python
if self.on_finish and not run.stopped:
    try:
        await self.on_finish(chat["id"], run)
    except Exception as e:
        print(f"on_finish failed: {type(e).__name__}: {e}")
```

### 5. Wire it in `app.py`

```python
subs = push.Subscriptions(config.DATA / "push.json")

async def notify(chat_id, run):
    if not subs.all():
        return
    try:
        chat = store.get(chat_id)
    except KeyError:
        return
    done = next((e for e in reversed(run.events) if e["type"] == "done"), None)
    payload = push.build_payload(chat, done, bool(cfg.get("push_show_titles")))
    await asyncio.to_thread(push.send_all, subs, payload, config.DATA, cfg["push_contact"])
```

Pass `on_finish=notify` to `RunManager`. Routes on the `api` router:

| Route | Body | Result |
|---|---|---|
| `GET /api/push/key` | | `{"publicKey": "..."}`; 501 `"Notifications need the push extra: ..."` if `PushUnavailable` |
| `POST /api/push/subscribe` | `{"subscription": {...}, "label": "..."}` | 200; 400 if invalid |
| `POST /api/push/unsubscribe` | `{"endpoint": "..."}` | 200 (also when unknown) |
| `POST /api/push/test` | | sends "Notifications are working" to all; returns `{"sent": n}` |

### 6. Service worker (`sw.js`)

Bump `CACHE` to the next version. Add:

```js
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { /* ignore */ }
  // Always show a notification: browsers (Safari especially) penalise silent pushes.
  e.waitUntil(self.registration.showNotification(d.title || 'agents-dialpad', {
    body: d.body || '', tag: d.tag || 'agents-dialpad', data: { url: d.url || '/' }, icon: '/icon-192.png', badge: '/icon-192.png',
  }));
});
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = new URL(e.notification.data.url, self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) { if ('focus' in w) { try { await w.navigate(url); } catch { /* ignore */ } return w.focus(); } }
    return clients.openWindow(url);
  })());
});
```

### 7. UI (`app.js`)

1. Helper `b64urlToUint8(s)` (pad, replace `-`/`_`, `atob`, to `Uint8Array`).
2. `pushSupported()`: `'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window`.
3. `async function enablePush()`:
   - not supported → if iOS (`/iPhone|iPad/.test(navigator.userAgent)`) and not standalone
     (`!matchMedia('(display-mode: standalone)').matches`) → `toast('On iPhone, add agents-dialpad to your Home Screen first, then open it from there.')`;
     else `toast("This browser can't receive notifications.")`.
   - `Notification.requestPermission()` must be called directly from the click handler (user gesture). Not granted →
     `toast('Notifications are blocked in your browser settings.')`.
   - `getJSON('/push/key')` (501 → toast the message), `navigator.serviceWorker.ready`,
     `reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64urlToUint8(publicKey) })`,
     `POST /push/subscribe` with `{subscription: sub.toJSON(), label: <short device label>}`.
   - `LS.set('ag_push', '1')`; `toast('Notifications on')`.
4. `async function disablePush()`: get the subscription, `POST /push/unsubscribe {endpoint}`, `sub.unsubscribe()`,
   `LS.del('ag_push')`, `toast('Notifications off')`.
5. Sidebar menu (`sideMenuItems()`): add **Turn on notifications** / **Turn off notifications** (icon `bell`:
   `<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>`) and, when on,
   **Send a test notification**.
6. The device label: `(navigator.userAgentData && navigator.userAgentData.platform) || (navigator.platform || 'device')`, max 40 characters.

## Tests

`tests/test_push.py` (unit, pywebpush is in the dev group):
1. `test_subscriptions_are_deduplicated_by_endpoint` and `test_remove_returns_false_for_unknown`.
2. `test_validate_subscription_rejects_bad_input`: http endpoint, missing keys, huge strings.
3. `test_payload_is_generic_by_default`; `test_payload_can_include_the_title`; `test_payload_for_errors_and_blocked_commands`.
4. `test_vapid_key_is_created_once_and_reused(tmp_path)`: two calls return the same key; the PEM file exists.
5. `test_send_all_removes_gone_subscriptions(monkeypatch)`: monkeypatch `push.webpush` to raise `WebPushException`
   with a fake response `status_code=410` for one endpoint and succeed for another → one removed, returns 1.

`tests/test_integration.py`:
6. `test_push_routes_need_the_token`.
7. `test_subscribe_validates_and_stores`.
8. `test_a_finished_reply_triggers_a_notification(monkeypatch)`: monkeypatch `push.send_all` to record payloads;
   subscribe a fake subscription; run a turn; wait until idle; exactly one payload with `tag` = chat id.
9. `test_stopped_replies_do_not_notify`.
10. `test_key_route_returns_501_without_pywebpush(monkeypatch)`: make `vapid_public_key` raise `PushUnavailable`.

## Manual check (needs a real phone)

1. Android Chrome or iPhone (Home Screen app), over the Tailscale HTTPS URL.
2. Sidebar More → Turn on notifications → allow. Send a test notification.
3. Start a long prompt, lock the phone, wait: notification appears; tapping it opens the chat.
4. If iPhone shows nothing and the server log shows **403 BadJwtToken**, Apple rejected the `push_contact` claim: set
   `"push_contact"` to a real `mailto:` address you own, restart, try again. Write what you found in the PR.

## Docs

README: "Notifications" section (how to install the extra, iPhone Home Screen requirement, privacy: generic text by
default, `push_show_titles`). SECURITY.md: push payloads go through the browser vendor's push service; content is
encrypted end-to-end by Web Push, and is generic unless `push_show_titles` is on. CHANGELOG. `config.example.json`.

## Acceptance checklist

- [ ] Works on a real Android phone and a real iPhone Home Screen app (state which you tested).
- [ ] Generic text by default; titles only with `push_show_titles`.
- [ ] Gone subscriptions are cleaned up; no endpoint or token in logs.
- [ ] Without the `push` extra, the app works and the menu explains how to enable notifications.

## Pitfalls

- `Notification.requestPermission()` outside a click handler is ignored on iOS.
- Do not send pushes from the event loop thread: `webpush` is blocking; use `asyncio.to_thread`.
- Bump the service-worker cache name or phones keep the old `sw.js` without the push handler.
