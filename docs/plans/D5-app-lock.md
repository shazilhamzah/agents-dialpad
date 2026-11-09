# D5. App lock with Face ID / fingerprint

- **Size:** L (two parts; hand them over one at a time)
- **Needs first:** B5 device tokens (merged); D4 if you want its "no action buttons when locked" rule filled in
- **Branches:** `spike/d5-webauthn`, `feat/d5-app-lock`
- **PR title:** `feat: lock the app with Face ID, Touch ID or fingerprint`

## Goal

The owner can turn on **App lock** for a phone. From then on, opening the app on that phone (or coming back to it after
a few minutes) shows a lock screen with one button, **Unlock**. It uses the phone's own Face ID, Touch ID, fingerprint or
screen PIN through a passkey (WebAuthn). Until it is unlocked, **the server refuses every API call from that phone**,
so the lock cannot be skipped by editing the page.

## Why

The app gives full control of the computer's coding agents, and with "Full access" it can run any command. Anyone holding
the unlocked phone (a friend, a child, a thief before the phone locks) can use it. The access token stays on the phone,
so today the only protection is the phone's own lock.

## Design (read before coding)

- **Library:** `webauthn` (py_webauthn, maintained by Duo Labs), as a new optional extra `lock = ["webauthn>=2"]`, also
  added to the `dev` group for CI. Without the extra, the menu item says "App lock needs the lock extra" with the install
  command.
- **Who has a lock:** an identity, meaning `"owner"` or a device id from B5. Each identity can register one or more
  passkeys. Stored in `<data>/lock.json`:
  `{"credentials": [{"who", "credential_id" (b64url), "public_key" (b64url), "sign_count", "rp_id", "name", "created"}]}`.
  This file holds no secrets that let anyone sign in (public keys only), but write it atomically like other files.
- **Relying party:** `rp_id` = the host name the app is opened on (`location.hostname`), for example
  `muhammad-shazil.tailb70ef8.ts.net` or `localhost`. A passkey made on one address does not work on another. That is
  fine and expected; the UI says which address the lock belongs to.
- **Allowed origins** (checked by the server on every WebAuthn verify): `http://localhost:<port>`,
  `http://127.0.0.1:<port>` and the Tailscale HTTPS URL from `pairing.tailscale_url`. WebAuthn only works in a secure
  context (HTTPS or localhost). Plain-HTTP LAN addresses cannot use App lock, and the UI must say so.
- **Unlock session:** a successful unlock returns `{"unlock": "<random 32 bytes, url-safe>", "expires_in": <seconds>}`.
  The server keeps only `sha256(unlock)` → `{who, last_used}` in memory. The app sends it on every request as header
  `X-Unlock`. It expires after `app_lock_idle_minutes` (config, default 5) without requests, and when the server restarts
  (memory only, so restarting the computer locks every phone, which is acceptable).
- **Enforcement:** in `identity()`, after the bearer token is matched: if that identity has at least one credential and
  the request is not under `/api/lock/` (and not `/api/info`, which the lock screen needs to show the app name), require a
  valid `X-Unlock` for the **same** identity, else `423 Locked` `{"detail": "locked"}`. The stream endpoint is included.
  A running stream simply continues until the run ends (same as revocation today).
- **Recovery:** lost passkey or new phone: the owner runs `agents-dialpad lock reset` (all identities) or
  `agents-dialpad lock reset --device <id>` on the computer. Revoking a device (UI or CLI) deletes its credentials.
  The owner token on the computer itself can always reset; the CLI never needs the passkey.
- **Push (D4):** `actions_allowed(sub)` returns False for subscriptions whose device has a lock. Notifications still
  arrive, without action buttons.

## Part 0: spike (no product code)

1. Write `tools/spikes/webauthn_page.html` plus a tiny FastAPI app in `tools/spikes/webauthn_spike.py` that does one
   register and one authenticate with py_webauthn (`generate_registration_options`, `verify_registration_response`,
   `generate_authentication_options`, `verify_authentication_response`, `options_to_json`). Check those names exist in
   the installed version; record the version.
2. Serve it with `tailscale serve` on a spare port. Run it on an **iPhone Home Screen web app**, an **Android Chrome Home
   Screen app** and **desktop Chrome on localhost**. For each, record: does the system Face ID / fingerprint sheet appear,
   does authenticate work after closing and reopening the Home Screen app, and what `PublicKeyCredential.
   isUserVerifyingPlatformAuthenticatorAvailable()` returns.
3. Write `docs/plans/D5-findings.md`. If the iPhone Home Screen app cannot use passkeys, stop and report; the plan then
   needs a different design (for example, a PIN checked by the server).

## Part 1: the feature

### 1. Server (`agents_dialpad/applock.py`, new)

- `class LockStore(path)`: `list(who)`, `add(who, cred)`, `remove(who, credential_id)`, `reset(who=None)`,
  `has_lock(who)`, `update_sign_count(...)`. Reload when the file changes on disk (the CLI edits it), the same way
  `devices.Devices` does.
- `class Sessions(idle_seconds)`: `create(who) -> token`, `check(token, who) -> bool` (constant-time compare of hashes,
  refreshes `last_used`), `drop_all(who)`.
- Pending challenges: in memory, keyed by a random challenge id, tied to `who`, single use, expire after 2 minutes.

Routes (all under `/api/lock/`, so they still need the bearer token, but not the unlock):

| Route | Does |
|---|---|
| `GET /api/lock/status` | `{"enabled": bool, "available": bool (extra installed), "secure_context_hint": str, "credentials": [{id, name, created}]}` for the caller |
| `POST /api/lock/register/options` | registration options (`userVerification: "required"`, `authenticatorAttachment: "platform"`, `residentKey: "preferred"`) |
| `POST /api/lock/register/verify` | verify, store the credential, and return an unlock session (the user just proved presence) |
| `POST /api/lock/unlock/options` | authentication options for the caller's credentials |
| `POST /api/lock/unlock/verify` | verify (`require_user_verification=True`), check and update `sign_count`, return a session |
| `DELETE /api/lock/credentials/{id}` | remove one of the caller's passkeys. **Needs a valid unlock**, so a thief cannot turn the lock off |

Rate limit unlock attempts per identity: at most 10 failed verifications per 10 minutes, then 429 for 10 minutes.

### 2. CLI

`agents-dialpad lock status` (lists identities with passkeys) and `agents-dialpad lock reset [--device ID]`.
`device revoke` also removes that device's passkeys.

### 3. Web app

1. Menu → **App lock**: shows status. If off: explanation and **Turn on** (runs register). If on: the list of passkeys
   with **Remove**, and the idle time. If not a secure context: "App lock needs the HTTPS address (Tailscale). Open the
   app from there."
2. `api()` wrapper: send `X-Unlock` when we have one (keep it in `sessionStorage` only, never `localStorage`). On a 423
   response, show the lock screen and retry the original request after unlocking.
3. Lock screen: full-screen overlay with the app icon, "Locked" and **Unlock** (≥ 44 px). It covers the chat content
   completely. Do not render chat titles behind it.
4. Lock again when the app has been hidden (`visibilitychange`) for longer than `app_lock_idle_minutes`: drop the
   session and show the lock screen on return. Tell the server too (`POST /api/lock/lock`, which drops the session).
5. Respect `prefers-reduced-motion`; the overlay must be reachable by screen readers (focus moves to Unlock).

### 4. Doctor

"App lock: on for owner and 2 devices" / "App lock: extra not installed" (info) / warn if `lock.json` names a device
that no longer exists.

## Tests

The WebAuthn ceremony needs a real authenticator, so tests use py_webauthn's verify functions with **recorded**
registration and authentication responses from the spike (store them in `tests/fixtures/webauthn/`, with the challenge
and origin they were made for) and monkeypatch challenge generation to return the recorded challenge.

- `test_lock_status_when_off_and_extra_missing`
- `test_register_then_api_requires_unlock` (after register: requests without `X-Unlock` → 423; with the session → 200)
- `test_unlock_with_recorded_assertion_returns_a_session`
- `test_wrong_origin_is_rejected`
- `test_session_expires_after_idle_time` (monkeypatch time)
- `test_session_of_one_device_does_not_unlock_another`
- `test_removing_a_passkey_needs_an_unlocked_session`
- `test_cli_reset_removes_the_lock_while_the_server_runs`
- `test_revoking_a_device_removes_its_passkeys`
- `test_failed_unlocks_are_rate_limited`
- `test_lock_routes_and_info_work_while_locked`

## Browser check (by hand)

On the real phones from the spike: turn on, lock by leaving the app for the idle time, unlock with Face ID/fingerprint,
remove the passkey, `lock reset` from the computer. On desktop Chrome on localhost, the same with the platform
authenticator (Windows Hello / Touch ID).

## Docs

`README.md`: App lock section (what it protects and what it does not, supported addresses, recovery with `lock reset`),
CLI table, configuration table (`app_lock_idle_minutes`), install with the `lock` extra. `SECURITY.md` if present.
`CHANGELOG.md`.

## Acceptance checklist

- [ ] With the lock on, no API call except `/api/info` and `/api/lock/*` succeeds without a fresh unlock.
- [ ] The lock cannot be turned off without unlocking (only `lock reset` on the computer bypasses it).
- [ ] Works on an iPhone Home Screen app, an Android app and desktop localhost (record any exception in the PR).
- [ ] Unlock sessions live in memory only, expire on idle, and are never written to disk or logs.
- [ ] Losing the phone or the passkey is recoverable from the computer in one command.
