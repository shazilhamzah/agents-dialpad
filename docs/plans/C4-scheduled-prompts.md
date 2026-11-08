# C4. Scheduled prompts

- **Size:** M
- **Needs first:** B1 for the notification (scheduling itself works without it)
- **Branch:** `feat/c4-schedules`
- **PR title:** `feat: run prompts on a schedule`

## Goal

The owner defines schedules in `config.json`, for example "every weekday at 08:00, ask Claude in my-app to summarise
yesterday's commits". At that time agents-dialpad creates a new chat named "<schedule name> · <date>", sends the
prompt, and (with B1) notifies when the reply is ready. The sidebar More menu gets **Schedules** with the list, the
next run time, and a **Run now** button.

## Config

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

- `at`: 24-hour local time `HH:MM`. `days`: list of `mon`…`sun`, or the string `"daily"`.
- `mode`: `readonly` or `edit` (and `ask` once C1 exists). `full` only if `allow_full_access` is true.
- Names must be unique (1–40 characters). Invalid schedules are skipped and reported by `doctor`.

## Read first

- `agents_dialpad/app.py` (`create_app`, `create_chat`, `send_message`), `agents_dialpad/runs.py`, `agents_dialpad/config.py`
- FastAPI "lifespan" events documentation (to start and stop a background task with the app)

## Steps

### 1. `agents_dialpad/schedules.py`

```python
def normalize(raw, cfg) -> tuple[list[dict], list[str]]:
    """Validate like quick commands (A4): clean list plus problems. Never raises."""

def next_run(s: dict, now: datetime) -> datetime:
    """Next local datetime at s['at'] on an allowed day, strictly after now."""

def is_due(s: dict, now: datetime, last_run_date: str | None, grace: timedelta = timedelta(hours=2)) -> bool:
    """True if today is an allowed day, now >= today's 'at', now - at <= grace, and last_run_date != today's date.
    The grace window covers a computer that was asleep at 'at' and woke up soon after; later than that, skip the day."""

class State:
    """<data>/schedules-state.json: {name: "YYYY-MM-DD" of the last run}."""
```

All date logic uses **local time** (`datetime.now()`), because users write local times.

### 2. Scheduler loop (`app.py`)

Use a FastAPI `lifespan` context manager in `create_app`: start `asyncio.create_task(loop())` on startup, cancel it on
shutdown. `loop()` every 30 seconds: for each schedule with `is_due(...)`: mark it run in `State` **first** (so a crash
cannot cause repeats), then call a shared helper `start_scheduled(s)` which creates the chat (provider, project, mode,
model from the schedule; title `f"{name} · {date}"`) and calls `runs.start(chat, prompt)`. If the project or agent is
not available, log one line and skip.

Expose `scheduler_tick(now)` (the body of one iteration) so tests can call it with a fixed time instead of waiting.

### 3. Routes

- `GET /api/schedules` → `[{"name", "next_run" (ISO local), "last_run", "project", "agent"}]`.
- `POST /api/schedules/{name}/run` → starts it now (ignores time and state, does update `last_run`) → `{"chat_id"}`.

### 4. UI

Sidebar More menu: **Schedules** (icon `clock`: `<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>`), only if
there is at least one schedule. Sheet: one row per schedule (name, "Next: Tue 08:00", "Last: yesterday"), and a
**Run now** button that opens the new chat. A note: "Edit schedules in config.json on the computer."

## Tests

`tests/test_schedules.py` (pure functions, fixed datetimes): weekday filtering, `daily`, exactly at the time, inside
and outside the grace window, already ran today, invalid entries reported, `full` refused without `allow_full_access`,
next_run across a week boundary.

Integration: config with a schedule due "now" (build `at` from a fixed `now` you pass to `scheduler_tick`) → one chat
created with the right title and the fake agent's reply; calling tick again the same day creates nothing;
`POST /api/schedules/<name>/run` works and needs the token.

## Docs

README: "Scheduled prompts" section with the example, the grace-window rule, and the note that the computer must be
awake (A1 keeps it awake only while a reply runs, not until the schedule time). CHANGELOG. `config.example.json`
(one disabled example, for instance with an empty `days` list, which normalize reports and skips).

## Acceptance checklist

- [ ] A schedule runs once per allowed day, never twice, even across restarts.
- [ ] Missed runs (computer asleep longer than the grace window) are skipped, not piled up.
- [ ] Full access is never reachable through a schedule unless enabled.
