"""Unit tests for scheduled prompts logic."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agents_dialpad.schedules import DAY_NAMES, State, is_due, next_run, normalize


def test_normalize_valid_and_defaults():
    cfg = {"projects": {"repo": "/path/to/repo"}, "allow_full_access": False}
    raw = [
        {
            "name": "Daily digest",
            "at": "09:30",
            "days": "daily",
            "project": "repo",
            "agent": "claude",
            "prompt": "Morning summary",
        },
        {
            "name": "Weekly review",
            "at": "17:00",
            "days": ["fri"],
            "project": "repo",
            "agent": "antigravity",
            "mode": "edit",
            "model": "gemini-pro",
            "prompt": "Summarize week",
        },
    ]
    valid, problems = normalize(raw, cfg)
    assert problems == []
    assert len(valid) == 2
    assert valid[0]["days"] == DAY_NAMES
    assert valid[0]["mode"] == "readonly"
    assert valid[0]["model"] == ""
    assert valid[1]["days"] == ["fri"]
    assert valid[1]["mode"] == "edit"


def test_normalize_reports_problems():
    cfg = {"projects": {"repo": "/path/to/repo"}, "allow_full_access": False}
    raw = [
        {"name": "", "at": "09:00", "days": "daily", "project": "repo", "agent": "claude", "prompt": "hi"},
        {"name": "Bad time", "at": "25:00", "days": "daily", "project": "repo", "agent": "claude", "prompt": "hi"},
        {"name": "Bad day", "at": "09:00", "days": ["funday"], "project": "repo", "agent": "claude", "prompt": "hi"},
        {"name": "Empty days", "at": "09:00", "days": [], "project": "repo", "agent": "claude", "prompt": "hi"},
        {"name": "Bad proj", "at": "09:00", "days": "daily", "project": "nonexistent", "agent": "claude", "prompt": "hi"},
        {"name": "Bad agent", "at": "09:00", "days": "daily", "project": "repo", "agent": "unknown", "prompt": "hi"},
        {"name": "Full denied", "at": "09:00", "days": "daily", "project": "repo", "agent": "claude", "mode": "full", "prompt": "hi"},
        {"name": "Empty prompt", "at": "09:00", "days": "daily", "project": "repo", "agent": "claude", "prompt": ""},
    ]
    valid, problems = normalize(raw, cfg)
    assert len(valid) == 0
    assert len(problems) >= 8

    # Duplicate names rejected
    dups = [
        {"name": "Dup", "at": "09:00", "days": "daily", "project": "repo", "agent": "claude", "prompt": "a"},
        {"name": "Dup", "at": "10:00", "days": "daily", "project": "repo", "agent": "claude", "prompt": "b"},
    ]
    valid_dups, dup_probs = normalize(dups, cfg)
    assert len(valid_dups) == 1
    assert any("duplicate" in p.lower() for p in dup_probs)


def test_full_access_allowed_when_configured():
    cfg = {"projects": {"repo": "/path/to/repo"}, "allow_full_access": True}
    raw = [{"name": "Full", "at": "08:00", "days": "daily", "project": "repo", "agent": "claude", "mode": "full", "prompt": "run"}]
    valid, problems = normalize(raw, cfg)
    assert problems == []
    assert len(valid) == 1
    assert valid[0]["mode"] == "full"


def test_is_due_and_grace():
    s = {"at": "08:00", "days": ["mon", "wed", "fri"]}
    # Mon at 08:00 exactly -> due
    dt_mon_0800 = datetime(2026, 11, 9, 8, 0)  # 2026-11-09 is a Monday
    assert is_due(s, dt_mon_0800, last_run_date=None) is True

    # Before at -> not due
    dt_mon_0759 = datetime(2026, 11, 9, 7, 59)
    assert is_due(s, dt_mon_0759, last_run_date=None) is False

    # Inside grace window (1h after 08:00) -> due
    dt_mon_0900 = datetime(2026, 11, 9, 9, 0)
    assert is_due(s, dt_mon_0900, last_run_date=None) is True

    # Outside grace window (2h1m after 08:00) -> not due (skipped)
    dt_mon_1001 = datetime(2026, 11, 9, 10, 1)
    assert is_due(s, dt_mon_1001, last_run_date=None) is False

    # Already ran today -> not due
    assert is_due(s, dt_mon_0900, last_run_date="2026-11-09") is False

    # Tuesday (not in allowed days) -> not due
    dt_tue_0800 = datetime(2026, 11, 10, 8, 0)
    assert is_due(s, dt_tue_0800, last_run_date=None) is False


def test_next_run():
    s = {"at": "08:00", "days": ["mon", "fri"]}
    # Currently Mon 07:00 -> next run is Mon 08:00
    now = datetime(2026, 11, 9, 7, 0)
    assert next_run(s, now) == datetime(2026, 11, 9, 8, 0)

    # Currently Mon 08:30 -> next run is Fri 08:00
    now = datetime(2026, 11, 9, 8, 30)
    assert next_run(s, now) == datetime(2026, 11, 13, 8, 0)

    # Across week boundary: Fri 09:00 -> next run is next Mon 08:00
    now = datetime(2026, 11, 13, 9, 0)
    assert next_run(s, now) == datetime(2026, 11, 16, 8, 0)


def test_state_persistence(tmp_path):
    path = tmp_path / "schedules-state.json"
    state = State(path)
    assert state.get("task1") is None

    state.set_run("task1", "2026-11-09")
    assert state.get("task1") == "2026-11-09"

    # Reload from disk
    state2 = State(path)
    assert state2.get("task1") == "2026-11-09"
    assert state2.all() == {"task1": "2026-11-09"}
