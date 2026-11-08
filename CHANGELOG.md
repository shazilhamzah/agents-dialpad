# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [semantic versioning](https://semver.org/) (0.x means the interface may still change).

## [Unreleased]

### Added
- **Push notifications:** Web Push notifications when a reply finishes, fails, or has blocked commands (requires optional extra gents-dialpad[push]).
- **Quick commands:** One-tap owner-defined command buttons configured in `config.json` (`quick_commands`).
- **Chat housekeeping:** rename, pin to top, search titles and message content, and export as Markdown.
- **QR code pairing:** `agents-dialpad pair` prints a QR code in the terminal; the sidebar **More → Pair a device**
  menu item shows the same code in the web app.
- Keeps the computer awake while an agent is working (`keep_awake`).
- **Installable package.** `uv tool install git+https://github.com/shazilhamzah/agents-dialpad` (or pipx) gives an
  `agents-dialpad` command; the UI ships inside the wheel. PyPI publishing is wired up and opt-in.
- **Command line:** `serve`, `init`, `project add|list|remove`, `token [--rotate]`, `doctor`, `autostart install|uninstall|status`.
- **Cross-platform auto-start:** Windows (scheduled task + watchdog, now windowless via `pythonw`), macOS (launchd,
  `KeepAlive`) and Linux (systemd user service, `Restart=always`). macOS/Linux files are unit-tested but not yet tried
  on real machines.
- **Per-user data folder** on every OS (`--data-dir` / `AG_DATA` to override; `./data` in a git checkout).
- **End-to-end tests with fake `claude` and `agy` CLIs** (send, stream, resume, stop, replay, restart, permissions) and a
  wheel smoke test; CI now also runs on macOS and on the oldest supported Python (3.11).
- `docs/remote-access.md`: Tailscale, Cloudflare Tunnel with Access, SSH tunnel, and what not to do.
- `AG_CLAUDE_ARGS` / `AG_AGY_ARGS` to put arguments after an agent executable (wrappers, tests).

### Changed
- The Python package is now `agents_dialpad` (was `gateway`); run it with `agents-dialpad` or `python -m agents_dialpad`.
- Relative project paths in `config.json` are now relative to the data folder.
- `serve` no longer prints the access token unless it is attached to a terminal (the token no longer lands in log files).
- `app.create_app()` builds an independent app, which is what lets the tests run many isolated apps.

### Fixed
- Merge-safe saving: a finishing reply no longer overwrites changes made meanwhile (such as a rename).

## [0.1.0] - 2026-11-08

First public release. **Early prototype, developed and tested on Windows 11 only.**

### Added
- Mobile-first web app (installable PWA) to chat with Claude Code and Antigravity running on your own computer.
- Per-chat agent, model, project folder and permission level (read-only, can edit, opt-in full access).
- Replies run in the background and survive phone lock or lost signal; stop button; conversation memory.
- Markdown rendering (headings, lists, tables, quotes, code with copy button) that never renders raw HTML or
  remote images.
- Responsive layout: one column on phones, two panes from tablet width; light/dark; reduced-motion support.
- Usage-limits viewer (Antigravity quota via its CLI; Claude Code windows from the last reply).
- Static access token, loopback-only server, Tailscale Serve setup guide.
- Optional always-on instructions file (example: `instructions/caveman.md`).
- Windows helpers: auto-start at sign-in/unlock, 5-minute watchdog, desktop shortcut, stop/restart scripts.
- 27 Python tests and 27 JavaScript tests; CI on Linux and Windows.

### Known gaps
- No in-app approve/deny for commands; Codex not implemented; no file upload or push notifications.
- Auto-start scripts are Windows-only; macOS and Linux are untested.
