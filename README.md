# agents-dialpad

Chat with the AI coding agents on your own computer (Claude Code and Antigravity today) from your phone.
Your computer stays on and logged in to the agents; agents-dialpad is a small web app that puts a mobile chat in
front of them.

```
Phone (installable PWA) ──private network (e.g. Tailscale)──► agents-dialpad (127.0.0.1:8787) ──► claude / agy CLIs
```

- One small Python process. No WSL, no tmux, no Docker, no build step for the UI.
- Replies keep running if your phone locks or loses signal, and re-attach when you come back.
- Pick the agent, model, project folder and permission level per chat. See your usage limits.
- Replies render as Markdown: headings, lists, tables, quotes and code blocks with a copy button. Raw HTML is
  escaped and remote images are never loaded.
- Responsive: one column on phones, a chat list plus conversation from tablet width up; follows light/dark,
  text size and reduced-motion settings.
- It never sees or stores your provider logins: it only launches the **official CLIs**, which authenticate
  exactly as they do in your terminal.

> **Status: early prototype.** Developed and tested on Windows 11 only. The core is plain Python and may run on
> macOS or Linux, but that is untested; the auto-start scripts are Windows-specific. Issues and PRs welcome.

> **Read [SECURITY.md](SECURITY.md) before exposing this to any network.** It starts agents that can edit files
> and (in "Full access") run commands on your machine.

agents-dialpad is an independent project and is not affiliated with or endorsed by Anthropic, Google, Tailscale, or
Dialpad, Inc.
"Claude Code", "Antigravity" and other product names belong to their owners.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- At least one agent CLI, installed and **already logged in** on this machine:
  [Claude Code](https://claude.com/claude-code) (`claude`) and/or Antigravity (`agy`)
- To use it from a phone: a private network path to your computer. [Tailscale](https://tailscale.com) is the
  recommended one (below).

## Quick start

```powershell
git clone https://github.com/shazilhamzah/agents-dialpad.git
cd agents-dialpad
uv sync
uv run python -m gateway
```

It prints a link like `http://127.0.0.1:8787/#token=...`. Open it once per device; the token is saved in that
browser and removed from the address bar. On first run it creates `data/` (config, token, chats), which is
git-ignored. Copy `config.example.json` to `data/config.json` to see the available settings.

## Use it from your phone (Tailscale)

1. Install Tailscale on the computer and the phone, signed in to the same tailnet, with HTTPS enabled in the
   Tailscale admin console.
2. On the computer, publish agents-dialpad on its **own HTTPS port** (this does not touch anything else you publish):
   ```powershell
   tailscale serve status                      # check what is already published first
   tailscale serve --bg --https=8443 8787
   ```
   Plain `tailscale serve --bg 8787` takes over port 443 and would replace anything already there. Undo with
   `tailscale serve --https=8443 off`.
3. On the phone, open `https://<your-machine>.<your-tailnet>.ts.net:8443/#token=<your token>`, then install it:
   iOS Safari → Share → Add to Home Screen; Android Chrome → menu → Install app.

Do **not** use Tailscale Funnel or port-forward agents-dialpad to the public internet.

## Start automatically (Windows)

A per-user scheduled task starts agents-dialpad when you **sign in** and when you **unlock** the computer. It is safe to
trigger repeatedly: if agents-dialpad is already up, the script exits without doing anything. The task also acts as a **watchdog**: every
5 minutes it checks again, so if agents-dialpad ever stops it is back within 5 minutes (while it is running, the tick is
ignored and costs nothing). It runs through `scripts/start-hidden.vbs` so no console window ever appears. Output goes to
`data/gateway.log`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1     # install / re-install
powershell -File scripts\stop.ps1                                          # stop it completely
powershell -File scripts\stop.ps1 -Restart                                 # restart (after editing config.json)
powershell -ExecutionPolicy Bypass -File scripts\uninstall-autostart.ps1   # remove
```

(`Stop-ScheduledTask` alone is not enough: it leaves the gateway process running.) Sleep pauses agents-dialpad and it
resumes on wake, but your phone cannot reach it while the computer sleeps. To use it with the lid closed, set
Windows power settings to never sleep when plugged in.

**Desktop shortcut.** `powershell -ExecutionPolicy Bypass -File scripts\create-shortcut.ps1` puts a *agents-dialpad*
icon on your Desktop. Double-clicking it starts the gateway if it is not running (and waits until it answers),
checks that Tailscale is connected and phone access is published, then opens agents-dialpad in your browser. It is safe
to click when everything is already running. The token is read from `data\token.txt` when you click, so it is not
stored in the shortcut.

## Configuration

Everything lives in `data/config.json` (see [`config.example.json`](config.example.json)). Restart after editing.

| Key | Meaning |
|---|---|
| `host`, `port` | Listen address. Keep `127.0.0.1` and put a private-network proxy in front. |
| `projects` | `name → folder`. The phone can only pick from this list, it can never type a path. Relative paths are relative to the agents-dialpad folder. |
| `token` | Optional fixed access token (16+ characters). |
| `instructions_file` | Optional text file added to every conversation. Default `null` (none). Re-read every turn. See below. |
| `allow_full_access` | `true` adds the **Full access** permission level (see below). Default off. |

### Access token

Static: generated once and reused on every run. Order of precedence: env var `AG_TOKEN`, then `"token"` in
`config.json`, then `data/token.txt` (created on first run; delete it to rotate).

### Models

Pick a model when starting a chat, or tap the model chip in a chat's header to switch; it applies from your next
message. Claude Code's list is in `gateway/providers/claude.py`; Antigravity's comes live from `agy models`.

### Always-on instructions

Off by default. Point `"instructions_file"` at any text file and its contents are added to every conversation
(Claude Code via `--append-system-prompt`; Antigravity has no such flag, so it is prefixed to the first message with a
short reminder after). `instructions/caveman.md` ships as an example: a terse-reply style condensed from the
open-source "caveman" Claude skill. Enable it with `"instructions_file": "instructions/caveman.md"`.

## Permissions

| Level | Claude Code | Antigravity | What the agent can do |
|---|---|---|---|
| Read-only | `--permission-mode plan` | `--mode plan` | read and search files |
| Can edit files | `--permission-mode acceptEdits` | `--mode accept-edits` | edit files; commands needing approval are blocked and listed under the reply |
| Full access *(opt-in)* | `--permission-mode bypassPermissions` | `--dangerously-skip-permissions` | run any command without asking |

Both CLIs run headless, so nobody can click "approve": in the first two levels any shell command that needs
approval is refused and shown as "blocked (needs approval)". Antigravity's `--mode auto` does not help, and its
`permissions.allow` rules matched unreliably in testing, so there is no dependable allowlist yet. Real
approve/deny buttons are on the roadmap.

**Full access** is off by default. Enable it with `"allow_full_access": true`, then choose it per chat. Anyone with
your token can then run commands on your machine, and a prompt-injected file in a repo could too. Only use it on
projects you trust.

## Usage limits

Tap **Limits**. Antigravity's quota (five-hour and weekly windows per model family) comes from `agy -p=/usage`
with no model call, cached for 60 s. Claude Code's windows come from the last reply it sent, so they appear after
your first Claude message.

## Layout

- `gateway/app.py`: HTTP API (`/api/...`, bearer token) and static files
- `gateway/runs.py`: background turns; they survive phone lock/disconnect and can be replayed
- `gateway/providers/`: one adapter per CLI (`claude.py`, `antigravity.py`); copy one to add another agent
- `static/`: the mobile PWA (plain HTML/CSS/JS); `markdown.js` is the dependency-free Markdown renderer
- `scripts/`: Windows auto-start helpers
- `tests/`: parser, config and storage tests (`uv run pytest`), Markdown tests (`node --test tests/js/markdown.test.js`)

## Known gaps

- Codex is not implemented yet (its `codex exec --json` mode is the likely route).
- Antigravity does not report tool output (only which tool ran) or cost.
- Antigravity prompts go on the command line, so messages over ~28k characters are rejected.
- No in-app approval prompts, file/image upload, or push notifications.
- Windows-only tested; the computer must stay awake and signed in.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
