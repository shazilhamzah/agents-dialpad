"""Tests for agents_dialpad.usage (UsageLog and summary aggregation)."""
import time
from datetime import datetime, timedelta
from agents_dialpad.usage import UsageLog


def test_usage_log_append_and_summary_with_fixed_now(tmp_path):
    log_file = tmp_path / "usage-log.jsonl"
    ulog = UsageLog(log_file)

    # Pick a fixed timestamp: 2026-11-09 12:00:00 local time
    fixed_now = datetime(2026, 11, 9, 12, 0, 0).timestamp()

    # Append entry for today
    ulog.append({
        "ts": fixed_now,
        "provider": "claude",
        "model": "claude-sonnet-5-5",
        "chat_id": "c1",
        "duration_ms": 1200,
        "input_tokens": 500,
        "output_tokens": 100,
        "cost_usd": 0.05,
        "is_error": False,
    })

    # Append error entry for today
    ulog.append({
        "ts": fixed_now + 10,
        "provider": "claude",
        "model": "claude-sonnet-5-5",
        "chat_id": "c2",
        "duration_ms": 400,
        "input_tokens": 50,
        "output_tokens": 10,
        "cost_usd": 0.01,
        "is_error": True,
    })

    # Append entry for 2 days ago
    two_days_ago = (datetime(2026, 11, 7, 10, 0, 0)).timestamp()
    ulog.append({
        "ts": two_days_ago,
        "provider": "antigravity",
        "model": "gemini",
        "chat_id": "c3",
        "duration_ms": 2000,
        "input_tokens": 800,
        "output_tokens": 200,
        "cost_usd": None,
        "is_error": False,
    })

    summary = ulog.summary(days=7, now=fixed_now)
    assert len(summary) == 7 * 3  # 7 days * 3 providers (claude, antigravity, codex)

    today_claude = next(s for s in summary if s["date"] == "2026-11-09" and s["provider"] == "claude")
    assert today_claude["replies"] == 2
    assert today_claude["input_tokens"] == 550
    assert today_claude["output_tokens"] == 110
    assert today_claude["errors"] == 1

    two_days_agy = next(s for s in summary if s["date"] == "2026-11-07" and s["provider"] == "antigravity")
    assert two_days_agy["replies"] == 1
    assert two_days_agy["input_tokens"] == 800
    assert two_days_agy["output_tokens"] == 200
    assert two_days_agy["errors"] == 0


def test_usage_missing_days_included_with_zeros(tmp_path):
    log_file = tmp_path / "usage-log.jsonl"
    ulog = UsageLog(log_file)
    fixed_now = datetime(2026, 11, 9, 12, 0, 0).timestamp()

    summary = ulog.summary(days=3, now=fixed_now)
    dates = sorted(list({s["date"] for s in summary}))
    assert dates == ["2026-11-07", "2026-11-08", "2026-11-09"]
    for s in summary:
        assert s["replies"] == 0
        assert s["input_tokens"] == 0
        assert s["output_tokens"] == 0
        assert s["errors"] == 0


def test_usage_prunes_older_than_90_days_at_startup(tmp_path):
    log_file = tmp_path / "usage-log.jsonl"
    now = time.time()
    old_ts = now - 95 * 86400
    recent_ts = now - 10 * 86400

    log_file.write_text(
        f'{{"ts": {old_ts}, "provider": "claude", "chat_id": "c_old", "is_error": false}}\n'
        f'{{"ts": {recent_ts}, "provider": "claude", "chat_id": "c_recent", "is_error": false}}\n',
        encoding="utf-8",
    )

    ulog = UsageLog(log_file)
    lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert "c_recent" in lines[0]
    assert "c_old" not in lines[0]
