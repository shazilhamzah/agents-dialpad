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
- **Project folders are an allowlist.** The phone can only choose folders listed in `config.json` (in the data folder); it
  cannot supply a path. The agent itself is not sandboxed to that folder by agents-dialpad.
- **Quick commands run with your full user rights, whatever the chat's permission level; only list commands you would run yourself.**
- **Push notifications travel through the browser vendor's push service** (Apple, Google, Mozilla). Payloads are end-to-end encrypted according to the Web Push standard (RFC 8291). Push bodies are generic by default (`Your reply is ready`) and do not disclose chat contents unless `push_show_titles` is set to true in `config.json`.
- **Desktop session previews:** Authenticated devices can list recent Claude Code sessions and read their first user prompt previews only for configured project folders.
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
