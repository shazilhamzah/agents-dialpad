# Feature plans

Step-by-step plans for the next features, written so that a coding assistant (or a new contributor) can implement them
one at a time without needing to understand the whole project first.

**Start here:** every task assumes you have read [00-rules-for-implementers.md](00-rules-for-implementers.md).

## The tasks

| ID | Feature | Size | Needs first | What the user gets |
|---|---|---|---|---|
| [A1](A1-keep-awake.md) | Keep the computer awake while an agent works | S | none | Replies no longer die because the laptop went to sleep mid-answer |
| [A2](A2-qr-pairing.md) | QR code pairing and a sidebar menu | S | none | Scan a QR code to connect a phone; no copying long links |
| [A3](A3-chat-housekeeping.md) | Rename, pin, search, export chats (+ safe saving) | S–M | none | Tidy chat list; find old answers; take a chat elsewhere as Markdown |
| [A4](A4-quick-commands.md) | Quick-command buttons | S–M | A3 | One-tap `git status`, `npm test`… defined by the owner |
| [B1](B1-push-notifications.md) | Push notifications | M | A2 | "Reply ready" on the lock screen |
| [B2](B2-change-viewer.md) | Change viewer (git diff + revert) | M | A3 | Review what the agent changed, from the phone |
| [B3](B3-desk-sessions.md) | Continue desktop sessions (and back) | M | A3 | Pick up a Claude Code session started at the desk |
| [B4](B4-uploads.md) | Upload screenshots and files | M | A3 | Send a screenshot or log file to the agent |
| [B5](B5-device-tokens.md) | One token per device, revocable | M | A2 | Lost phone? Revoke just that phone |
| [C1](C1-approvals.md) | Approve / deny commands from the phone | L | B1 (optional) | Commands no longer just "blocked"; you decide |
| [C2](C2-codex.md) | Codex as a third agent | M–L | none | Use Codex the same way |
| [C3](C3-usage-and-alerts.md) | Usage history and limit alerts | M | B1 | See usage per day; warned before hitting a limit |
| [C4](C4-scheduled-prompts.md) | Scheduled prompts | M | B1 | "Every morning at 8, summarise yesterday's commits" |
| [C5](C5-compare-agents.md) | ~~Ask two agents at once~~ (removed by D1) | M–L | A3 | |
| [C6](C6-small-extras.md) | Per-project instructions | S | none | Different house rules per project |
| [D1](D1-remove-compare.md) | Remove the compare view | S–M | PR #5 merged | A simpler chat screen |
| [D2](D2-full-command-in-approvals.md) | Full command on approval cards | S | none | See exactly what you are allowing (and Antigravity cards stop being blank) |
| [D3](D3-codex-without-a-plan.md) | Codex readiness, friendly errors, default model | M | none | Codex greyed out with a hint instead of failing with raw JSON |
| [D4](D4-lock-screen-approvals.md) | Allow / Deny from the notification | M | D2 | Decide without opening the app (Android, desktop); iPhone jumps to the card |
| [D5](D5-app-lock.md) | App lock with Face ID / fingerprint | L | B5 | Someone holding your unlocked phone can't use your agents |
| [E0–E6](E-delegation-router.md) | Delegation router: Groq / Gemini free tiers, then Azure AI Foundry | XL (split) | D5 | Bulky coding work goes to cheap models through MCP; quotas, spend and jobs visible and editable in the app |

Sizes: **S** under a day, **M** a few days, **L** a week or more, for an experienced developer.

## Recommended order

1. **A1 → A2 → A3 → A4** (Phase A): small, safe, each one useful on its own. A3 contains a fix to how chats are saved
   that later tasks rely on, so do it before anything in phase B.
2. **B1 → B2 → B3 → B4 → B5** (Phase B).
3. **C1** needs a short research spike first (its plan says exactly what to check). Then C2, C3, C4, C5, C6 in any order.
4. **D1 → D2 → D3 → D4 → D5** (Phase D). D1 first because it shrinks the chat screen code the others touch. D2 before D4
   (the notification shows the command D2 normalises). D3 is independent. D5 needs its spike first, and fills in D4's
   "no notification buttons on locked phones" rule.
5. **E0 → E1 → E2 → E3 → E4 → E5 (→ E6)** (Phase E). E0 is a spike with real keys that corrects the plan before any
   code. E1–E3 make it usable from Claude Code; E4–E5 add the dashboard and editing from the phone. E6 is optional.

Dependencies that matter:
- **A2** creates the sidebar "More" menu and makes the menu code work for more than one button. B1, B5 and C3 add items to it.
- **A3** makes saving a chat merge-safe (a running reply no longer overwrites changes made meanwhile). B2, B3, B4 and C5 assume this.
- **B1** (push) is used by C1, C3 and C4 to notify. Without B1 those features still work, just without notifications.

## How to hand a task to a coding assistant

Copy this prompt, replacing `<ID>` and `<FILE>`:

```text
You are implementing one task in the agents-dialpad repository.

1. Read docs/plans/00-rules-for-implementers.md completely. Those rules are mandatory.
2. Read docs/plans/<FILE> completely, then every file it lists under "Read first".
3. Create the branch named in the task from the latest main and run the baseline tests.
4. Do the "Verify first" checks. If anything differs from what the task expects, stop and tell me exactly what you saw.
5. Implement the steps in order. After each step, run the checks that step lists.
6. Add every test listed under "Tests". Do not remove or weaken existing tests.
7. Update the docs listed in the task.
8. Finish with the task's acceptance checklist and the definition of done from the rules file, ticked, plus anything you
   could not do or test. Do not merge.

Implement only task <ID>. Do not start other tasks or refactor unrelated code.
```

Tips for the person supervising:
- Give the assistant one task at a time and review the PR before the next one.
- If the assistant reports that a "Verify first" check failed, that is a success: it avoided building on a wrong assumption.
  Update the task file with what was found before continuing.
- Large tasks (C1, D5) are split into numbered parts. You can hand over one part at a time.

## Progress

- [x] A1 Keep awake
- [x] A2 QR pairing + sidebar menu
- [x] A3 Chat housekeeping + safe saving
- [x] A4 Quick commands
- [x] B1 Push notifications
- [x] B2 Change viewer
- [x] B3 Desktop sessions
- [x] B4 Uploads
- [x] B5 Device tokens
- [x] C1 Approvals (spike → Claude → Antigravity)
- [x] C2 Codex
- [x] C3 Usage and alerts
- [x] C4 Scheduled prompts
- [x] C5 Compare agents (removed by D1)
- [x] C6 Per-project instructions
- [x] D1 Remove compare
- [x] D2 Full command on approval cards
- [x] D3 Codex readiness
- [x] D4 Allow / Deny from the notification
- [x] D5 App lock (spike → feature)
- [ ] E0 Router spike
- [ ] E1 Router core + CLI
- [ ] E2 Validation gate + apply
- [ ] E3 MCP server + delegate skill
- [ ] E4 Router dashboard
- [ ] E5 Editing from the frontend
- [ ] E6 Router as a chat agent (optional)
