# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [semantic versioning](https://semver.org/) (0.x means the interface may still change).

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
