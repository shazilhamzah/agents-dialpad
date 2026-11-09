# D4. Allow or Deny straight from the notification

- **Size:** M
- **Needs first:** D2 (approval events carry `command` and `description`); B1 push and C1 approvals (already merged)
- **Branch:** `feat/d4-notification-approvals`
- **PR title:** `feat: approve or deny commands from the notification`

## Goal

When an agent asks for approval, the push notification says **which agent wants to run what**, and, where the phone
supports it, has **Allow** and **Deny** buttons. Pressing one decides the request without opening the app. A second
notification confirms the result ("Allowed", "Denied", or "Already decided").

Where buttons are not supported (iPhone and iPad web apps, see below), tapping the notification opens the chat and
scrolls to the approval card, which is highlighted.

## Why

Approvals wait up to 10 minutes and then count as Deny. Today the notification only says "An agent needs your
approval". The user must unlock the phone, open the app, find the chat and scroll. Often they are too late.

## Platform facts (check these in "Verify first"; do not assume)

- Notification action buttons (`actions` in `showNotification`) work in Chrome on Android and desktop browsers.
  `Notification.maxActions` tells how many (usually 2).
- iOS/iPadOS Home Screen web apps show web push notifications but **do not show action buttons**. They get the
  "tap opens the card" behaviour.
- The service worker **cannot read `localStorage`**, where the app keeps its access token. It must not get the
  long-lived token. That is why this plan uses a one-time action token (below).

## Security design (read before coding)

1. When the server sends an approval notification, it creates an **action token** for that one request:
   `secrets.token_urlsafe(32)`. It keeps only its SHA-256 hash, in memory, on the `Run`, keyed by `req_id`, with the
   chat id. The plain token goes only into the push payload, which Web Push encrypts end to end (RFC 8291). The push
   service cannot read it.
2. A new route, **outside** the bearer-protected `/api` router: `POST /push-action` with JSON
   `{"chat": "<chat id>", "req": "<request id>", "token": "<action token>", "allow": true|false}`.
   - Validate `chat` with the chat-id regex and `req` with `REQ_ID_RE`. Limit the body to 1 KB.
   - Find the active run of that chat. Compare `sha256(token)` with the stored hash using `secrets.compare_digest`.
   - Unknown chat, no active run, unknown request or wrong token: always the **same** response, 404 `{"ok": false}`.
     Do not reveal which part was wrong.
   - Already decided: 409 `{"ok": false, "reason": "already_decided"}`.
   - Success: `run.decide(req, allow)` and record `by: "notification"` in the `approval_result` event.
   - The token is single use. Delete the hash on first use, on decision through the app, on timeout and when the run ends.
3. **Allow from the lock screen needs the command to be visible.** The notification shows the command only when the
   owner opts in with `push_show_commands: true` (default `false`, like `push_show_titles`). If commands are not shown,
   the notification has only **Deny** and **Open** buttons. Allowing something you cannot see is not offered.
4. Devices with the D5 app lock turned on get no action buttons (the app lock would be pointless if the lock screen
   could approve). Until D5 exists, ignore this point, but keep the check in one place (`actions_allowed(sub)`), so D5
   only fills it in.
5. Revoked devices get no notifications at all (already handled by the subscription `keep` filter).

## Read first

- `agents_dialpad/app.py`: `notify_approval`, `decide_approval`, `REQ_ID_RE`, `subs`, the `/api` router setup
- `agents_dialpad/runs.py`: `Run.pending`, `Run.decided`, `Run.decide`, `wait_decision`, `kill`
- `agents_dialpad/push.py`: `send_all`, `build_payload`
- `agents_dialpad/static/sw.js`: `push` and `notificationclick` handlers
- `agents_dialpad/static/app.js`: the router (`#/c/<id>`), the approval card markup from D2

## Verify first

1. In Chrome on an Android phone (Home Screen app over the Tailscale HTTPS address), run in the console of the app:
   `Notification.maxActions`. Expect 2 or more.
2. On an iPhone Home Screen app, check that `Notification.maxActions` is 0 or undefined.
3. In `sw.js`, check that `self.registration.showNotification(title, { actions: [...] })` with an unsupported platform
   simply ignores `actions` (no exception). Record results in the PR description.

## Steps

### 1. Server

1. `config.load()`: `cfg.setdefault("push_show_commands", False)`.
2. `Run`: add `action_tokens: dict[str, str]` (req_id → sha256 hex). Clear an entry in `decide`, in the timeout path of
   `wait_decision`, and clear all in `kill` and when the run finishes.
3. `notify_approval(chat_id, run, ev)`: create the token, store its hash, and build the payload:
   ```python
   {
     "title": f"{provider_label} wants to run a command",   # or "...wants to edit a file" for Edit/Write tools
     "body": first 160 chars of ev["command"] if push_show_commands else "Open to see what it wants to do",
     "tag": f"approval:{chat_id}:{req_id}",
     "url": f"/#/c/{chat_id}?approval={req_id}",
     "approval": {"chat": chat_id, "req": req_id, "token": plain_token, "can_allow": push_show_commands},
   }
   ```
   Payloads are limited to about 4 KB after encryption; keep the body short. Send it in a worker thread like today.
4. Add `POST /push-action` on the app (not on `api`) as described in the security design. Wrap it in the same
   1 KB body limit and return JSON. Log only `chat`, `req` and the outcome, **never the token**.
5. When a request is decided through the app (`decide_approval`), drop its action token too.

### 2. Service worker (`sw.js`)

1. In `push`: if `d.approval` is present, call `showNotification` with `requireInteraction: true` (stays until handled
   on desktop), `data: {url, approval}` and
   `actions: d.approval.can_allow ? [{action: 'allow', title: 'Allow'}, {action: 'deny', title: 'Deny'}] : [{action: 'deny', title: 'Deny'}, {action: 'open', title: 'Open'}]`.
2. In `notificationclick`: if `e.action` is `allow` or `deny`, `fetch('/push-action', {method: 'POST', headers:
   {'Content-Type': 'application/json'}, body: JSON.stringify({...approval, allow: e.action === 'allow'})})` inside
   `e.waitUntil`. Then show a short follow-up notification with the **same tag** (it replaces the first):
   "Allowed", "Denied", "Already decided in the app", or "Couldn't reach your computer. Open the app to decide."
   Do not open a window for these two actions. Any other click (`open` or the body) keeps today's behaviour: focus or
   open the window at `data.url`.
3. Bump the cache name (`agents-dialpad-shell-v3`) so phones pick up the new worker.

### 3. Web app

1. Router: accept `#/c/<id>?approval=<req>`. After the chat renders, scroll the matching approval card into view and give
   it a highlight class for 2 seconds (respect `prefers-reduced-motion`).
2. When the user decides in the app, close a matching notification if it is still shown:
   `(await navigator.serviceWorker.ready).getNotifications({tag})` then `.close()`.
3. A card decided from a notification shows "Allowed from notification" or "Denied from notification" (uses
   `by: "notification"`).

## Tests

- `test_push_action_allows_with_the_right_token` (integration with fake Claude `NEEDS_APPROVAL`; capture the payload by
  monkeypatching `push.send_all`; then POST `/push-action` with no Authorization header → 200, run continues, chat
  records `by: "notification"`).
- `test_push_action_token_is_single_use` (second POST → 409).
- `test_push_action_wrong_token_unknown_chat_and_unknown_request_look_the_same` (all 404 with identical bodies).
- `test_push_action_token_dies_when_decided_in_app` (decide via `/api/.../approvals/...`, then POST → 409 or 404, never 200).
- `test_push_action_after_timeout_is_rejected` (`AG_APPROVAL_TIMEOUT=1`).
- `test_command_is_only_in_the_payload_when_opted_in` (and `can_allow` follows the setting).
- `test_push_action_rejects_bodies_over_1kb`.
- `test_token_is_never_logged` (capture logs / stdout around a full flow and assert the plain token is absent).

## Browser check (by hand)

Desktop Chrome on `http://127.0.0.1:<port>` with notifications enabled: approval notification shows Deny/Open (default)
and Allow/Deny with `push_show_commands: true`; Allow from the notification lets the run finish; the follow-up
notification says "Allowed"; tapping the body opens the chat at the highlighted card. If you can, repeat on an Android
phone and confirm an iPhone shows the notification without buttons and opens the card.

## Docs

`README.md` notifications section: the buttons, the `push_show_commands` setting and why Allow needs it, the iPhone
limitation. Configuration table. `CHANGELOG.md`. `SECURITY.md` (if present): the one-time action token.

## Acceptance checklist

- [ ] Android and desktop: Allow/Deny work from the notification without opening the app.
- [ ] iPhone: tapping opens the chat at the highlighted approval card.
- [ ] Allow is never offered when the command is not shown.
- [ ] Action tokens are single use, die with the request, are compared in constant time, and are never logged.
- [ ] Nothing in `/push-action` accepts or reveals the long-lived access token.
