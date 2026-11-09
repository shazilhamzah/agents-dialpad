"""Scheduled prompts running on local time."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, time, timedelta
from pathlib import Path

log = logging.getLogger("agents-dialpad.schedules")

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_MAP = {name: idx for idx, name in enumerate(DAY_NAMES)}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def normalize(raw: object, cfg: dict) -> tuple[list[dict], list[str]]:
    """Validate raw schedule definitions against config. Never raises.

    Returns (valid_schedules, problems).
    """
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["Schedules configuration must be a list."]

    valid: list[dict] = []
    problems: list[str] = []
    seen_names: set[str] = set()

    projects = cfg.get("projects") or {}
    allow_full = bool(cfg.get("allow_full_access"))

    for idx, item in enumerate(raw):
        prefix = f"Schedule #{idx + 1}"
        sched_problems: list[str] = []
        if not isinstance(item, dict):
            problems.append(f"{prefix}: must be an object.")
            continue

        name = str(item.get("name") or "").strip()
        if not (1 <= len(name) <= 40):
            sched_problems.append(f"{prefix}: 'name' must be 1 to 40 characters.")
        elif name in seen_names:
            sched_problems.append(f"{prefix} ('{name}'): duplicate schedule name.")

        at = str(item.get("at") or "").strip()
        if not TIME_RE.match(at):
            sched_problems.append(f"Schedule '{name}': 'at' must be a 24-hour time in HH:MM format.")

        raw_days = item.get("days")
        days: list[str] = []
        if raw_days == "daily":
            days = list(DAY_NAMES)
        elif isinstance(raw_days, list):
            for d in raw_days:
                if isinstance(d, str) and d.lower() in DAY_MAP:
                    if d.lower() not in days:
                        days.append(d.lower())
                else:
                    sched_problems.append(f"Schedule '{name}': unknown day '{d}'. Must be one of {', '.join(DAY_NAMES)}.")
            if not days:
                sched_problems.append(f"Schedule '{name}': 'days' list cannot be empty.")
        else:
            sched_problems.append(f"Schedule '{name}': 'days' must be 'daily' or a list of weekday names.")

        project = item.get("project")
        if not isinstance(project, str) or project not in projects:
            sched_problems.append(f"Schedule '{name}': unknown project '{project}'.")

        agent = item.get("agent") or item.get("provider")
        disabled_agents = set(cfg.get("disabled_agents", []))
        if not isinstance(agent, str) or agent not in {"claude", "antigravity", "codex"}:
            sched_problems.append(f"Schedule '{name}': unknown agent '{agent}'. Must be claude, antigravity, or codex.")
        elif agent in disabled_agents:
            sched_problems.append(f"Schedule '{name}': agent '{agent}' is turned off in config.json.")

        mode = item.get("mode") or "readonly"
        if mode not in {"readonly", "edit", "full"}:
            sched_problems.append(f"Schedule '{name}': invalid mode '{mode}'.")
        elif mode == "full" and not allow_full:
            sched_problems.append(f"Schedule '{name}': mode 'full' requires 'allow_full_access: true' in config.")

        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            sched_problems.append(f"Schedule '{name}': 'prompt' must be a non-empty string.")

        if sched_problems:
            problems.extend(sched_problems)
            continue

        seen_names.add(name)
        valid.append({
            "name": name,
            "at": at,
            "days": days,
            "project": project,
            "agent": agent,
            "mode": mode,
            "model": str(item.get("model") or ""),
            "prompt": prompt.strip(),
        })

    return valid, problems


def next_run(s: dict, now: datetime) -> datetime:
    """Next local datetime at s['at'] on an allowed day, strictly after now."""
    hour, minute = map(int, s["at"].split(":"))
    allowed_days = set(s.get("days", []))
    for offset in range(8):
        cand_date = (now + timedelta(days=offset)).date()
        cand_day_name = DAY_NAMES[cand_date.weekday()]
        if cand_day_name in allowed_days:
            cand_dt = datetime.combine(cand_date, time(hour, minute))
            if cand_dt > now:
                return cand_dt
    return now + timedelta(days=1)


def is_due(
    s: dict,
    now: datetime,
    last_run_date: str | None,
    grace: timedelta = timedelta(hours=2),
) -> bool:
    """True if today is an allowed day, now >= today's 'at', now - at <= grace, and last_run_date != today's date."""
    today_str = now.strftime("%Y-%m-%d")
    if last_run_date == today_str:
        return False
    day_name = DAY_NAMES[now.weekday()]
    if day_name not in s.get("days", []):
        return False
    hour, minute = map(int, s["at"].split(":"))
    at_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < at_dt:
        return False
    if (now - at_dt) > grace:
        return False
    return True


class State:
    """<data>/schedules-state.json: {name: "YYYY-MM-DD" of the last run}."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.state: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.state = {str(k): str(v) for k, v in raw.items()}
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, name: str) -> str | None:
        return self.state.get(name)

    def set_run(self, name: str, date_str: str) -> None:
        self.state[name] = date_str
        self._save()

    def all(self) -> dict[str, str]:
        return dict(self.state)
