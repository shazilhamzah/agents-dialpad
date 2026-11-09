# agents-dialpad

Chat with the AI coding agents on your own computer (Claude Code, Antigravity and Codex) from your phone.
Your computer stays on and logged in to the agents; agents-dialpad is a small web app that puts a mobile chat in
front of them.

```
Phone (installable PWA) ──private network (e.g. Tailscale)──► agents-dialpad (127.0.0.1:8787) ──► claude / agy / codex CLIs
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

> **Status: early prototype.** Real agents are tested on Windows 11. The test suite (with fake agents) runs in CI on
> Windows, macOS and Linux, and the macOS/Linux auto-start files are generated and unit-tested but have not been tried
> on real machines yet. Issues and PRs welcome.

> **Read [SECURITY.md](SECURITY.md) before exposing this to any network.** It starts agents that can edit files
> and (in "Full access") run commands on your machine.

agents-dialpad is an independent project and is not affiliated with or endorsed by Anthropic, Google, Tailscale, or
Dialpad, Inc. "Claude Code", "Antigravity" and other product names belong to their owners.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/) (or pipx)
- At least one agent CLI, installed and **already logged in** on this machine:
  [Claude Code](https://claude.com/claude-code) (`claude`), Antigravity (`agy`), and/or [Codex](https://github.com/openai/codex) (`codex`)
- To use it from a phone: a private network path to your computer. [Tailscale](https://tailscale.com) is the
  recommended one; see [docs/remote-access.md](docs/remote-access.md) for the options.

## Install and run

```bash
uv tool install git+https://github.com/shazilhamzah/agents-dialpad   # installs the `agents-dialpad` command
agents-dialpad init       # creates the data folder; asks which project folders the phone may use
agents-dialpad doctor     # checks your agent CLIs, config and Tailscale, and tells you what to fix
agents-dialpad serve      # starts it and prints a link
```

Open the printed link (`http://127.0.0.1:8787/#token=...`) once per device. The token is saved in that browser and
removed from the address bar. Once the package is on PyPI the first line becomes `uv tool install agents-dialpad`.

Other ways to run it:

```bash
uvx --from git+https://github.com/shazilhamzah/agents-dialpad agents-dialpad serve   # try it without installing
git clone https://github.com/shazilhamzah/agents-dialpad.git && cd agents-dialpad && uv sync && uv run agents-dialpad serve
```

### Commands

| Command | What it does |
|---|---|
| `agents-dialpad serve [--port N]` | Start the server (also what plain `agents-dialpad` does). Exits quietly if it is already running. |
| `agents-dialpad init [--project NAME=PATH]` | Create the data folder and choose project folders. |
| `agents-dialpad project add\|list\|remove` | Manage the folders the phone can pick. |
| `agents-dialpad token [--rotate]` | Show the access token (and the link for a device), or replace it. |
| `agents-dialpad pair [--png FILE]` | Print a QR code (and link) to connect a phone without typing the URL. |
| `agents-dialpad device add|list|revoke` | Manage revocable per-device tokens. |
| `agents-dialpad doctor` | Check Python, config, agent CLIs, the port and Tailscale. Exit code 1 if something blocks you. |
| `agents-dialpad autostart install\|uninstall\|status` | Start automatically at login (below). `--dry-run` shows what would change. |

Global option: `--data-dir PATH` (or the `AG_DATA` environment variable) chooses where config, token and chats live.
The default is a per-user folder (Windows `%LOCALAPPDATA%\agents-dialpad`, macOS `~/Library/Application Support/agents-dialpad`,
Linux `~/.local/share/agents-dialpad`), or `./data` when you run from a git checkout.

## Use it from your phone

Short version with Tailscale (full guide, with alternatives: [docs/remote-access.md](docs/remote-access.md)):

1. Install Tailscale on the computer and the phone, signed in to the same tailnet, with HTTPS enabled in the Tailscale admin console.
2. On the computer, publish agents-dialpad on its **own HTTPS port** (this does not touch anything else you publish):
   ```bash
   tailscale serve status                      # check what is already published first
   tailscale serve --bg --https=8443 8787
   ```
3. Run `agents-dialpad pair` and scan the QR code with your phone's camera (or open
   `https://<your-machine>.<your-tailnet>.ts.net:8443/#token=<your token>`), then install it:
   iOS Safari → Share → Add to Home Screen; Android Chrome → menu → Install app.

Do **not** use Tailscale Funnel or port-forward agents-dialpad to the public internet.

## Start automatically

```bash
agents-dialpad autostart install      # then: status, uninstall
```

Install agents-dialpad permanently first (`uv tool install` or `pipx install`), not through `uvx`: the service points at the
Python that ran the command, and `uvx` environments are temporary.

| OS | What is registered | Restarts if it stops? |
|---|---|---|
| Windows | A per-user scheduled task: at sign-in (+20 s), at unlock, and a 5-minute watchdog tick. Runs windowless (`pythonw`). | Yes, within 5 minutes |
| macOS | A launchd agent (`~/Library/LaunchAgents/io.github.shazilhamzah.agents-dialpad.plist`) with `KeepAlive`. | Yes, immediately |
| Linux | A systemd user service (`~/.config/systemd/user/agents-dialpad.service`) with `Restart=always`. Run `loginctl enable-linger $USER` to keep it running when you are logged out. | Yes, after 5 s |

Background output goes to `gateway.log` in the data folder, and the access token is never written to it. While at least
one agent reply is running, agents-dialpad asks the OS not to idle-sleep (disable with `"keep_awake": false`). Closing a
laptop lid is still controlled by your OS power settings, and your phone cannot reach the computer while it sleeps.

**Extra Windows helpers (in a git checkout, `scripts/`):**
`launch.ps1` (start everything, check Tailscale, open the app), `create-shortcut.ps1` (puts an *agents-dialpad* icon on your
Desktop that runs it), `stop.ps1 [-Restart]` (stop completely; `Stop-ScheduledTask` alone leaves the server running).

## Configuration

Everything lives in `config.json` in the data folder (see [`config.example.json`](config.example.json)). Restart after editing.

| Key | Meaning |
|---|---|
| `host`, `port` | Listen address. Keep `127.0.0.1` and put a private-network proxy in front. |
| `projects` | `name → folder` path or object with `{"path": "...", "instructions_file": "..."}`. The phone can only pick from this list, it can never type a path. Relative paths are relative to the data folder. Manage with `agents-dialpad project`. |
| `token` | Optional fixed access token (16+ characters). |
| `instructions_file` | Optional text file added to every conversation. Default `null` (none). Re-read every turn. See below. |
| `keep_awake` | Prevent idle sleep while an agent reply is running. Default `true`. |
| `allow_full_access` | `true` adds the **Full access** permission level (see below). Default off. |
| `approval_timeout_seconds` | Seconds to wait for command approvals in "Ask me before commands" mode before auto-denying (default 600). Overridden by `AG_APPROVAL_TIMEOUT`. |
| `push_show_titles` | Include chat title in push notifications (`false` by default for privacy). |
| `push_contact` | VAPID `sub` claim (`mailto:` address). Default: `mailto:agents-dialpad@example.com`. |
| `codex_models` | List of model names to offer for Codex chats (default `[]` offers "Default"). |

### Access token

Static: generated once and reused on every run. Order of precedence: env var `AG_TOKEN`, then `"token"` in
`config.json`, then `token.txt` in the data folder (created on first run). `agents-dialpad token --rotate` replaces it.

### Models

Pick a model when starting a chat, or tap the model chip above the message box to switch; it applies from your next
message. Claude Code's list is in `agents_dialpad/providers/claude.py`; Antigravity's comes live from `agy models`;
Codex offers "Default" plus any models configured in `"codex_models"`.

### Always-on instructions

Off by default. Point `"instructions_file"` at any text file (absolute, relative to the data folder, or one of the examples
shipped in the package) and its contents are added to every conversation (Claude Code via `--append-system-prompt`;
Antigravity and Codex have no such flag, so it is prefixed to the first message with a short reminder after).
`instructions/caveman.md` ships as an example: a terse-reply style condensed from the open-source "caveman" Claude skill.
Enable it with `"instructions_file": "instructions/caveman.md"`.

In addition to global instructions, each project can define its own instruction file:

```json
"projects": {
  "workspace": "workspace",
  "my-app": {
    "path": "C:\\code\\my-app",
    "instructions_file": "C:\\code\\my-app\\.agents-dialpad.md"
  }
}
```

When present, project instructions are appended after the global instructions, separated by a blank line. Both files are re-read on every turn.

### Advanced: wrapping an agent CLI

`AG_CLAUDE` / `AG_AGY` / `AG_CODEX` choose the executable; `AG_CLAUDE_ARGS` / `AG_AGY_ARGS` / `AG_CODEX_ARGS` (a JSON list)
add arguments right after it, for example to run an agent through a wrapper. The test suite uses this to drive fake agents.

## Permissions

| Level | Claude Code | Antigravity | Codex | What the agent can do |
|---|---|---|---|---|
| Read-only | `--permission-mode plan` | `--mode plan` | `-s read-only` | read and search files |
| Can edit files | `--permission-mode acceptEdits` | `--mode accept-edits` | `-s workspace-write` | edit files; commands needing approval are blocked and listed under the reply |
| Ask me before commands | `--permission-mode default` + host prompts | `agy acp` (default mode) | not available yet | edit files, prompts for confirmation before running commands |
| Full access *(opt-in)* | `--permission-mode bypassPermissions` | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | run any command without asking |

When using **Ask me before commands** (Claude Code and Antigravity), shell commands and tools that require confirmation display an interactive card in the chat with **Allow** and **Deny** buttons. If push notifications are enabled, a notification is sent to your device with the command details. Unanswered requests time out and auto-deny after 10 minutes (configured via `approval_timeout_seconds` in `config.json` or the `AG_APPROVAL_TIMEOUT` environment variable). For Antigravity, "Ask me before commands" drives `agy acp` over the Agent Client Protocol (ACP).

In **Read-only** and **Can edit files**, any command that requires interactive approval is refused and shown as "blocked (needs approval)".

**Full access** is off by default. Enable it with `"allow_full_access": true`, then choose it per chat. Anyone with
your token can then run commands on your machine, and a prompt-injected file in a repo could too. Only use it on
projects you trust.

## Quick commands

The owner can define one-tap command buttons in `config.json` (global under `"*"` or per project):

```json
"quick_commands": {
  "*": [ { "label": "Git status", "run": ["git", "status", "--short"] } ],
  "my-app": [ { "label": "Run tests", "run": ["npm", "test"], "timeout": 300 } ]
}
```

In a chat, tap **More → Quick commands** to run them in the chat's project folder and view the output.
**These run with your full user rights, whatever the chat's permission level; only list commands you would run yourself.**

## Push notifications

agents-dialpad can send a Web Push notification when a reply finishes, fails, or has blocked commands.

1. Install the optional push dependency:
   ```bash
   uv tool install --upgrade "agents-dialpad[push]"
   # or with pip: pip install "agents-dialpad[push]"
   ```
2. In the web app, open sidebar **More (top right) → Turn on notifications** and allow permissions.
3. Test with **More → Send a test notification**.

> [!NOTE]
> On iPhone/iPad, Web Push only works when added to the Home Screen: in Safari, tap Share → Add to Home Screen, then launch the app from your Home Screen.
>
> For privacy, push messages are generic by default (`Your reply is ready`). Enable `"push_show_titles": true` in `config.json` if you want the chat title included.

## Usage limits and history

Tap **Limits**. Antigravity's quota (five-hour and weekly windows per model family) comes from `agy -p=/usage`
with no model call, cached for 60 s. Claude Code's windows come from the last reply it sent, so they appear after
your first Claude message.

The **Last 7 days** section shows daily replies and tokens per agent. When a subscription window drops below `limit_alert_percent` (default 20; set `0` to disable), you get one push notification for that window if notifications are on (see above), and never twice for the same window.

## Organising chats

- **Rename:** In a chat, tap **More → Rename** to give it a descriptive name.
- **Pin:** Tap **More → Pin** to keep important conversations at the top of your chat list.
- **Search:** Use the search bar above the chat list to search across titles, user messages and agent replies.
- **Export:** Tap **More → Export as Markdown** to download the whole conversation as a clean `.md` file.

## Continue between desk and phone

Work started at your computer can be picked up on your phone, and vice-versa (Claude Code):

- **Desk to phone:** When creating a new Claude chat, tap **Continue a desktop session** to pick from recent sessions in that project folder. The phone resumes that session (`claude --resume <id>`).
- **Phone to desk:** In any Claude chat, tap **More → Continue on the computer** to copy the terminal command (`claude --resume <id>`) to run at your desk.

## Devices

Each phone or tablet can have its own revocable token:

- **Add a device:** In the web app on your computer, open **More → Devices → Add a device**, or run `agents-dialpad device add "My Phone"` (or `agents-dialpad pair --device "My Phone"`).
- **Revoke a device:** In the Devices menu on your computer (or via `agents-dialpad device revoke <id>`), tap **Revoke**. That device is signed out immediately.
- **Migration advice:** After pairing your phones as individual devices, run `agents-dialpad token --rotate` on the computer. The old shared token stops working, while individual devices continue uninterrupted.

## Attachments

Tap the paperclip icon next to the message field to attach screenshots, logs, or documents:

- **Supported formats:** Images (`png`, `jpg`, `jpeg`, `gif`, `webp`, `heic`), documents (`pdf`, `txt`, `md`, `csv`, `json`, `log`, `yaml`, `yml`, `xml`), and code files (`html`, `css`, `js`, `ts`, `py`).
- **Limits:** Up to 15 MB per file, max 10 files per message, and 200 MB per chat.
- **Storage:** Files are stored in `<data>/uploads/<chat-id>/` (outside project folders) and passed to the agent via `--add-dir`. Deleting a chat deletes its uploads.

## Reviewing changes

After an agent edits files, tap **More → Changes** in that chat to review what changed:

- View modified, added, deleted, renamed and untracked files compared to the last git commit.
- Tap any file to inspect its unified diff with color-coded additions and deletions.
- For tracked files, tap **Revert this file** (with confirmation) to restore the file back to `HEAD`.
- Reverting is blocked while an agent is actively running in that project.

## Scheduled prompts

You can schedule recurring prompts in `config.json`:

```json
"schedules": [
  {
    "name": "Morning summary",
    "at": "08:00",
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "project": "my-app",
    "agent": "claude",
    "mode": "readonly",
    "model": "",
    "prompt": "Summarise yesterday's commits in this repository in five bullet points."
  }
]
```

- **Grace window:** A 2-hour grace window covers a computer that was asleep at `at` and woke up shortly after. If the computer was asleep longer than 2 hours past `at`, that day's run is skipped rather than piling up overdue runs.
- **Awake requirement:** The host computer must be awake at the scheduled time (or wake within the 2-hour grace window) for the schedule to trigger.
- **UI:** If schedules are configured, a clock icon appears in the header and More menu with next run times and a **Run now** button.

## Compare agents

When two or more agents are available, choose **Both (compare)** in the New chat sheet. It creates linked chats for both agents in the same project and opens a compare view:
- On screens under 1000 px, a tab bar lets you switch between agent conversations, showing activity dots while an agent is generating.
- On screens 1000 px and wider, both agent conversations render side-by-side.
- A single composer sends the prompt to both agents simultaneously. Both stream and can be stopped together.


## Project layout

- `agents_dialpad/app.py`: HTTP API (`/api/...`, bearer token) and static files; `create_app()` builds an independent app
- `agents_dialpad/runs.py`: background turns; they survive phone lock/disconnect and can be replayed
- `agents_dialpad/providers/`: one adapter per CLI (`claude.py`, `antigravity.py`, `codex.py`); copy one to add another agent
- `agents_dialpad/cli.py`, `doctor.py`, `autostart.py`: the command line
- `agents_dialpad/static/`: the mobile PWA (plain HTML/CSS/JS); `markdown.js` is the dependency-free Markdown renderer
- `scripts/`: extra Windows helpers for a git checkout
- `tests/`: unit tests, end-to-end tests with fake agents (`uv run pytest`), Markdown tests (`node --test tests/js/markdown.test.js`)
- `tools/`: icon generator and the wheel smoke test used by CI

## Known gaps

- Antigravity does not report tool output (only which tool ran) or cost.
- Antigravity prompts go on the command line, so messages over ~28k characters are rejected.
- No in-app approval prompts.
- Real agents are only tested on Windows; the computer must stay awake and signed in.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
