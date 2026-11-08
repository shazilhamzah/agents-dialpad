# C3. Usage history and limit alerts

- **Size:** M
- **Needs first:** B1 for the alerts (the history works without it)
- **Branch:** `feat/c3-usage`
- **PR title:** `feat: usage history and low-limit alerts`

## Goal

1. Every finished reply is logged locally (agent, model, duration, tokens when known, error or not).
2. The Limits sheet gets a **Last 7 days** section: replies and tokens per day per agent, as simple bars.
3. When a subscription window drops below a threshold (default 20 % left), the phone gets one notification per window.

## Read first

- `agents_dialpad/providers/claude.py` and `antigravity.py` (`_Parser`, the `result` handling)
- `agents_dialpad/runs.py` (`_drive`, `usage`), `agents_dialpad/app.py` (`limits`, `claude_limits`)
- `agents_dialpad/push.py` (B1), `agents_dialpad/static/app.js` (`openLimits`, `limitsHTML`)

## Steps

### 1. Tokens in the `done` event

- Claude: the `result` line has a `usage` object (`input_tokens`, `output_tokens`, cache fields). Add
  `"input_tokens"` and `"output_tokens"` to the `done` event (sum `input_tokens` + `cache_read_input_tokens` +
  `cache_creation_input_tokens` for input, if present). Keep `cost_usd`.
- Antigravity: the `result` has `usage` with `input_tokens`, `output_tokens` (seen in real output). Same fields.
- Update `tests/test_parsers.py` with these fields.

### 2. Usage log `agents_dialpad/usage.py`

```python
class UsageLog:
    """<data>/usage-log.jsonl, one JSON object per finished reply. Lines older than 90 days are pruned at startup."""
    def append(self, entry: dict) -> None: ...
    def summary(self, days: int = 7, now: float | None = None) -> list[dict]:
        """[{"date": "YYYY-MM-DD" (local time), "provider", "replies", "input_tokens", "output_tokens", "errors"}], oldest first, missing days included with zeros."""
```

`RunManager` gets an `on_finish` list (or reuse B1's hook) that appends
`{"ts", "provider", "model", "chat_id", "duration_ms", "input_tokens", "output_tokens", "cost_usd", "is_error"}`.
Stopped replies are logged with `"stopped": true`.

### 3. Route

`GET /api/usage?days=7` (1–90) → `{"days": summary}`.

### 4. Alerts `agents_dialpad/alerts.py`

```python
def windows_below(limits: list[dict], threshold: int) -> list[dict]:
    """From the rows shown in the Limits sheet (provider, group, label, remaining, resets_at) return those with remaining < threshold."""

class AlertState:
    """<data>/alerts.json: which (provider, group, label, resets_at) were already alerted, so each window alerts once."""
```

Check after every finished reply (Claude rows come from `runs.usage`; for Antigravity call `limits(force=False)`, which
is cached for 60 s). For each new low window send one push (B1): title "agents-dialpad", body
"<Agent> <window>: <n>% left" (no conversation content). Config: `limit_alert_percent` (default 20; `0` disables).

### 5. UI

Limits sheet, under the existing windows: heading "Last 7 days" and, per day, one row: the date ("Mon 3"), then one bar
per agent whose width is proportional to replies (max of the period = 100 %), with the number at the end
(`tabular-nums`). Tokens shown as "12.4k tokens" when known. Use existing tokens (`--ok` for bars is fine; add
`--bar-2` for the second agent, light and dark values, 3:1 contrast against `--surface-2`).

## Tests

`tests/test_usage.py`: append/summary with fixed `now`, missing days, pruning, local-date bucketing.
`tests/test_alerts.py`: threshold, once per window, new window after reset alerts again, `0` disables.
Integration: a fake claude turn appends one log line with tokens; `/api/usage` returns it; with a monkeypatched push
sender and a fake rate-limit event at 10 % left, exactly one alert is sent across two turns.

## Docs

README: Limits section update, `limit_alert_percent`. CHANGELOG. `config.example.json`.

## Acceptance checklist

- [ ] Log contains no prompt or reply text.
- [ ] One alert per window, never repeated for the same window.
- [ ] Works (history only) without the push extra.
