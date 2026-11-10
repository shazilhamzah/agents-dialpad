# Security

agents-dialpad gives a web page the ability to start coding agents on your computer. Treat it like remote shell
access and deploy it accordingly.

## Threat model

- **Anyone who has your access token controls your agents.** In "Full access" that means running commands as
  your user. The token is a bearer secret; keep it out of screenshots, chat logs and shared links.
- **Never expose agents-dialpad to the public internet.** Run it on `127.0.0.1` behind a private network such as
  Tailscale (use `tailscale serve`, not Funnel). There is no rate limiting, no per-user accounts and no audit log.
- **Prompt injection is real.** An agent that reads an untrusted file, web page or repo can be told to do
  things. In "Full access" it can act on them without asking. Use "Read-only" or "Can edit files" for untrusted
  projects.
- **Command approvals:** "Ask me before commands" mode prompts for interactive confirmation before commands run. Approval endpoints (`POST /api/chats/{id}/approvals/{req_id}`) require bearer authentication. Approval requests are never auto-allowed; unanswered requests time out and auto-deny after 10 minutes (`approval_timeout_seconds` or `AG_APPROVAL_TIMEOUT`). Stopping a run cancels any pending approvals immediately. "Full access" mode remains available for trusted setups where prompt confirmation is unnecessary, but is rarely needed.
- **Lock-screen approval action tokens:** Approving or denying commands from push notifications uses a short-lived, single-use action token generated per approval request. Only the SHA-256 hash of the token is kept in server memory on the active run. The plain token travels solely inside the end-to-end encrypted push payload (RFC 8291). The endpoint (`POST /push-action`) requires the token, verifies it in constant time (`secrets.compare_digest`), destroys the token hash immediately on first use or resolution, and never exposes or requires the long-lived access token. Allow action buttons are never provided unless the command preview is visible (`push_show_commands: true`).
- **App lock (passkeys):** Turning on App lock enforces WebAuthn biometric verification (Face ID, Touch ID, fingerprint) for that identity. When enabled, all API endpoints except `/api/info` and `/api/lock/*` return `423 Locked` unless an active `X-Unlock` session token is presented. Unlock sessions live exclusively in server memory, expire after `app_lock_idle_minutes` (default 5), and are never written to disk. Push action buttons are automatically withheld for subscriptions whose device has App lock enabled. Failed unlock attempts are rate-limited to 10 attempts per 10 minutes (returning 429). Passkeys can always be reset from the host computer via `agents-dialpad lock reset` or device revocation without needing the passkey.
- **Project folders are an allowlist.** The phone can only choose folders listed in `config.json` (in the data folder); it
  cannot supply a path. The agent itself is not sandboxed to that folder by agents-dialpad.
- **Quick commands run with your full user rights, whatever the chat's permission level; only list commands you would run yourself.**
- **Push notifications travel through the browser vendor's push service** (Apple, Google, Mozilla). Payloads are end-to-end encrypted according to the Web Push standard (RFC 8291). Push bodies are generic by default (`Your reply is ready`) and do not disclose chat contents unless `push_show_titles` is set to true in `config.json`.
- **Desktop session previews:** Authenticated devices can list recent Claude Code sessions and read their first user prompt previews only for configured project folders.
- **File viewer read access:** Authenticated devices can browse and preview project folder files. Access is strictly read-only and restricted inside the chosen project root. Access to internal app state (`<data>/`), `.git/` folder contents, and secret patterns (`.env`, `*.pem`, `*.key`, `id_rsa*`, etc.) is denied (returning 404). Executable web formats (`.html`, `.svg`, `.js`, etc.) are served with strict `sandbox` CSP and `text/plain` content types for viewing to prevent script execution in the app's origin. Uvicorn access logs on the host machine may log requested file paths in query strings; bearer tokens never appear in URLs. File browsing can be disabled globally via `"file_viewer": false`.
- **Uploaded files:** Files and screenshots attached in chats are stored unencrypted in the data folder and are readable by the agent via `--add-dir`.
- **Per-device tokens:** Each device can hold its own token. Only the SHA-256 hash is saved in `devices.json`. Adding and revoking devices requires the owner token.
- **Provider logins are never read.** agents-dialpad only launches the official CLIs. It stores chat transcripts and
  your token in the data folder, unencrypted, so protect that folder like any other secret. Background services run with
  `--quiet`, so the token is never written to their logs; `agents-dialpad token` prints it on demand.
- The token travels in the URL **fragment** (`#token=`), which browsers do not send to servers, and is removed
  from the address bar after first use. API calls use an `Authorization` header.

## Supported versions

Only the latest commit on the default branch is supported while the project is a prototype.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting: the repository's **Security** tab →
**Report a vulnerability**. Include what you found, how to reproduce it, and the impact. You should get a first
response within a few days; this is a volunteer project, so there is no guaranteed timeline.
