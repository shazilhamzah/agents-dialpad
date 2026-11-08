# B5. One token per device, revocable

- **Size:** M
- **Needs first:** A2 (pairing and the sidebar More menu)
- **Branch:** `feat/b5-devices`
- **PR title:** `feat: per-device tokens that can be revoked`

## Goal

Each phone or tablet gets its own token. The owner can see the list of devices (with "last used") and revoke one,
without changing the token on every other device. The existing token becomes the **owner token**: it keeps working,
lives on the computer, and is the only one allowed to add or revoke devices.

## Why

Today a lost phone means rotating the single token and re-pairing everything.

## Design

- `<data>/devices.json`: `{"devices": [{"id": "8 hex", "name": "...", "token_sha256": "hex", "created": t, "last_seen": t|null}]}`.
  **Only the SHA-256 of a device token is stored.** The token itself is shown once (as a QR/link) and never again.
- Auth accepts the owner token or any device token. The request's identity is `"owner"` or the device id.
- Adding and revoking devices requires the owner token. A device can see the list.

## Read first

- `agents_dialpad/app.py` (`require_token`, `api` router), `agents_dialpad/config.py`, `agents_dialpad/pairing.py` (A2),
  `agents_dialpad/cli.py` (`pair`), `agents_dialpad/static/app.js` (`sideMenuItems`, `openPair`)

## Steps

### 1. New module `agents_dialpad/devices.py`

```python
class Devices:
    def __init__(self, path: Path): ...
    def list(self) -> list[dict]: ...                       # without token_sha256
    def add(self, name: str) -> tuple[dict, str]: ...        # returns (record, plaintext token); name 1-40 chars
    def revoke(self, device_id: str) -> bool: ...
    def match(self, token: str) -> str | None: ...           # device id or None; compare hashes with secrets.compare_digest
    def touch(self, device_id: str) -> None: ...             # set last_seen; write to disk at most once per 5 minutes per device
```

Write the file atomically (temp file + `os.replace`). Read with `utf-8-sig`.

### 2. Identity dependency (`app.py`)

Replace `require_token` with:

```python
def identity(authorization: str | None = Header(default=None)) -> str:
    supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if supplied and secrets.compare_digest(supplied.encode(), token.encode()):
        return "owner"
    dev = devices.match(supplied) if supplied else None
    if dev:
        devices.touch(dev)
        return dev
    raise HTTPException(401, "Invalid or missing token")

def owner_only(who: str = Depends(identity)) -> str:
    if who != "owner":
        raise HTTPException(403, "Only the owner token can do this. Use the computer, or `agents-dialpad device`.")
    return who
```

The router keeps `dependencies=[Depends(identity)]` (FastAPI caches the dependency per request, so routes can also
take `who: str = Depends(identity)` without running it twice).

### 3. Routes

| Route | Who | Result |
|---|---|---|
| `GET /api/devices` | any | `{"devices": [...], "me": "<owner or device id>"}` |
| `POST /api/devices` body `{"name"}` | owner | `{"device": {...}, "url": <pair link with the NEW token>, "qr": <data URI>}` |
| `DELETE /api/devices/{id}` | owner | 200 / 404 |

`GET /api/info` also returns `"me"`. `GET /api/pair` (from A2) becomes owner-only, since it reveals the owner token.

### 4. CLI

`agents-dialpad device add NAME [--no-qr] [--png FILE]` (prints the QR and link for the new device, once),
`agents-dialpad device list`, `agents-dialpad device revoke ID`. Add `"device"` to `COMMANDS`.
`agents-dialpad pair --device NAME` creates a device and shows its QR instead of the owner token's.

### 5. UI

Sidebar More menu: **Devices** (icon `phone`: `<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>`).
Sheet:
- one row per device: name, "Last used 3h ago" / "Never used", and **This device** if it is `me`;
- if `me === "owner"`: a **Revoke** button per row (confirm: "Revoke <name>? It will be signed out immediately.") and
  **Add a device** (asks for a name, then shows the QR sheet from A2 using the returned `url`/`qr`);
- if `me` is a device: a note "Devices can only be added or revoked from the computer."

### 6. Migration advice (docs only)

After pairing each phone as a device, the owner can run `agents-dialpad token --rotate` so the old shared token stops
working on phones. The owner token stays on the computer (the Desktop shortcut reads it from `token.txt`).

## Tests

`tests/test_devices.py` (unit): add returns a token whose hash is stored and the token itself is **not** in the file;
match/revoke; names validated; touch throttling (monkeypatch time).

`tests/test_integration.py`:
1. `test_device_token_can_use_the_api`.
2. `test_revoked_device_token_is_rejected` (401 right after DELETE).
3. `test_devices_cannot_add_or_revoke` (403).
4. `test_pair_link_is_owner_only` (403 for a device).
5. `test_info_reports_who_is_calling`.

## Manual check

Pair a phone as a device with `agents-dialpad pair --device "My phone"`; use it; revoke it from the computer's browser;
the phone gets the "token was rejected" screen on its next action.

## Docs

README: "Devices" section and the migration advice. SECURITY.md: per-device tokens, hashes only, owner-only actions.
CHANGELOG.

## Acceptance checklist

- [ ] devices.json never contains a plaintext token.
- [ ] Revocation is immediate (no restart).
- [ ] Owner-only routes refuse device tokens.
- [ ] Existing setups keep working without any change (the owner token still works everywhere).

## Pitfalls

- Use `secrets.compare_digest` on the hex digests, not `==`.
- Do not write devices.json on every request; the 5-minute throttle matters on a busy phone.
