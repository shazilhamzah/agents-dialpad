# D3. Make Codex behave well when the account cannot use it

- **Size:** M
- **Needs first:** nothing
- **Branch:** `feat/d3-codex-readiness`
- **PR title:** `feat: clear Codex status, friendly errors and a default-model setting`

## Goal

Codex is installed on many computers whose account cannot actually run it (no paid ChatGPT plan, not signed in, or a
default model in `~/.codex/config.toml` that the account may not use). Today the app still offers Codex, and the first
message fails with raw JSON such as:

```text
{"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-6.1-sol' model is not supported
when using Codex with a ChatGPT account.","code":"model_not_found"}}
```

After this task:

1. The app knows whether Codex is **ready**, **not signed in**, or **unknown**, and shows it in the agent picker
   ("Codex (sign in on the computer)") instead of failing later.
2. Errors from Codex are turned into one plain sentence with what to do next, plus a button where it helps
   (**Change model**).
3. The owner can pick the model the app uses for Codex (`codex_default_model`), so the app works even when
   `~/.codex/config.toml` names a model the account may not use.
4. The owner can hide any agent they do not use: `"disabled_agents": ["codex"]`.
5. `agents-dialpad doctor` explains Codex's state and the fix.

What this task **cannot** do: make Codex work without an account that OpenAI allows to use it. The README must say the two
ways to get access: a ChatGPT plan that includes Codex, or an OpenAI API key (`codex login --with-api-key`, billed per use).

## Read first

- `agents_dialpad/providers/codex.py` (`available`, `models`, `stream`, the parser's `error` / `turn.failed` handling)
- `agents_dialpad/providers/__init__.py` (`PROVIDERS`), `agents_dialpad/app.py` (`/api/info`, `create_chat`,
  `check_model`), `agents_dialpad/doctor.py`, `agents_dialpad/config.py` (`load`)
- `docs/plans/C2-findings.md` (what Codex prints), `tests/fake_agents/fake_codex.py`, `tests/fixtures/codex/`
- `agents_dialpad/static/app.js`: `openNewChat`, `openModel` (the model sheet), how `error` events render

## Verify first (spike; record results in `docs/plans/D3-findings.md`)

Run each command on a computer with Codex installed, once **signed in** and once **signed out** (`codex logout`, then
`codex login` again afterwards). Record stdout, stderr and exit code exactly.

1. `codex login status`
2. `codex --version`
3. `codex exec --json --skip-git-repo-check -s read-only "Reply with OK"` with no `-m` (uses `~/.codex/config.toml`).
4. The same with `-m <a model the account can use>`.
5. If you can (ask the owner), the same with an account that is signed in but has **no plan**, and with an API-key login.

Stop and report if `codex login status` does not exist or does not tell signed-in from signed-out. Then use whatever
does (for example, the presence of `~/.codex/auth.json`), and write down what you chose and why.

## Steps

### 1. Readiness

1. Add to every provider a method `async def status(self) -> dict` returning
   `{"state": "ready" | "not_installed" | "not_signed_in" | "unknown", "note": "<short user-facing hint or ''>"}`.
   Default implementation (base class or each provider): `not_installed` when `available()` is False, otherwise `ready`.
2. Codex: run `codex login status` (exec, no shell, 10 s timeout, kill the process tree on timeout like other calls).
   Map the outputs you recorded to the states. Cache the result for 5 minutes; a failed run is `unknown` (never blocks).
3. `/api/info`: each provider gets `status` and `note`. Keep `available` for old clients (`available` = state is not
   `not_installed` and the agent is not disabled).
4. `create_chat`: refuse a provider whose state is `not_signed_in` with
   400 "Codex isn't signed in on the computer. Run `codex login` there, then try again." (`unknown` is allowed.)

### 2. Settings

In `config.load()`:

- `cfg.setdefault("disabled_agents", [])`. Validate it is a list of known provider names; ignore unknown names and report
  them in doctor. Disabled agents disappear from `/api/info` and `create_chat` refuses them (400 "This agent is turned off
  in config.json"). Existing chats with a disabled agent still open read-only: the composer shows "Codex is turned off in
  config.json" instead of the input.
- `cfg.setdefault("codex_default_model", "")`. When a Codex chat has model `""` (Default) and this is set, pass
  `-m <codex_default_model>`. Validate it with the same `MODEL_RE` used for chat models, and add it to the Codex model list
  if it is not already there. The model sheet's "Default" label becomes "Default (<model>)" when this is set.

### 3. Friendly errors

Add `codex_error_text(raw: str) -> tuple[str, str | None]` (message, action) in `providers/codex.py`:

1. If `raw` parses as JSON (it often is JSON inside a string), read `error.code`, `error.message`, `status`.
2. Map:
   | Matches | Message | Action |
   |---|---|---|
   | code `model_not_found`, or "model is not supported" | "Your Codex account can't use the model '<m>'. Pick another model, or set `codex_default_model` in config.json." | `change_model` |
   | status 401, or "not logged in" / "unauthorized" | "Codex isn't signed in on the computer. Run `codex login` there." | none |
   | status 429, or "usage limit" / "rate limit" | "Codex usage limit reached. Try again later or use another agent." | none |
   | "plan" / "subscription" / "upgrade" | "Your OpenAI account doesn't include Codex. Use a plan that includes it, or sign in with an API key (`codex login --with-api-key`)." | none |
   | anything else | `error.message` if present, else the first 300 characters of `raw` | none |
3. Emit `{"type": "error", "message": ..., "action": "change_model"}` (omit `action` when none). On `not_signed_in`
   or 401 also drop the cached status so the picker updates.
4. Web app: an error with `action: "change_model"` shows a **Change model** button under the message that opens the
   existing model sheet for this chat.

### 4. Web app picker

`openNewChat`: list agents in `/api/info` order. For a provider whose `status.state` is `not_signed_in`, the option is
`disabled` and labelled "Codex (sign in on the computer)"; `not_installed` stays "(not installed)". If the first agent is
not usable, select the first usable one. When the owner taps a disabled option nothing happens (native behaviour), so
also show the `note` under the Agent select when such an agent exists.

### 5. Doctor

One line per agent: ok "Codex: signed in (ChatGPT)" / warn "Codex: not signed in. Run `codex login`" / warn "Codex: model
'<m>' from ~/.codex/config.toml may not be allowed for your account; set codex_default_model" (only if the spike shows a
reliable way to detect this; otherwise skip that check) / info "Codex: turned off in config.json".

## Tests

Extend `tests/fake_agents/fake_codex.py`: env `FAKE_CODEX_LOGIN=signed_in|signed_out` controls `codex login status`
output (copy the real outputs from the findings), and a prompt containing `MODEL_NOT_ALLOWED` makes it print the
`model_not_found` error recorded above.

- `test_codex_status_signed_in_and_out` (unit, with the fake).
- `test_codex_status_is_cached` (second call within 5 minutes does not start a process; count calls via `FAKE_LOG`).
- `test_info_reports_status_and_hides_disabled_agents`.
- `test_create_chat_refuses_signed_out_codex` (400 with the message above).
- `test_codex_default_model_is_passed_when_chat_model_is_default` (check argv in `FAKE_LOG`).
- `test_codex_error_text_maps_known_errors` (table-driven: every row of the mapping table).
- `test_model_not_found_error_has_change_model_action` (integration, `MODEL_NOT_ALLOWED`).
- `test_unknown_disabled_agent_names_are_reported_by_doctor`.

## Browser check (by hand, 375 px)

With the fake signed out: Codex is greyed out with the hint. Signed in + `MODEL_NOT_ALLOWED`: the error is one sentence
and **Change model** opens the model sheet. With `"disabled_agents": ["codex"]`: Codex is gone from New chat.

## Docs

- `README.md`: Codex section: the two ways to get access, what "sign in on the computer" means,
  `codex_default_model` and `disabled_agents` in the configuration table.
- `config.example.json`: both keys with comments in the README (JSON has no comments).
- `CHANGELOG.md`.

## Acceptance checklist

- [ ] With Codex signed out, the app never lets you start a Codex chat that is sure to fail.
- [ ] No raw JSON error reaches the chat for the error kinds in the table.
- [ ] `codex_default_model` works without editing `~/.codex/config.toml`.
- [ ] `disabled_agents` hides an agent everywhere new chats are started (New chat sheet, schedules validation).
- [ ] Status checks never block a page load for more than 10 seconds, and are cached.
