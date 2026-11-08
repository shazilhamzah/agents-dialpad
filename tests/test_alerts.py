"""Tests for agents_dialpad.alerts (rate-limit window alerts)."""
from agents_dialpad.alerts import AlertState, check_alerts, windows_below


def test_windows_below_threshold():
    limits = [
        {
            "name": "claude",
            "label": "Claude Code",
            "rows": [
                {"group": "Claude Code", "label": "5-hour", "remaining": 15, "resets_at": "2026-11-09T14:00:00Z"},
                {"group": "Claude Code", "label": "Weekly", "remaining": 50, "resets_at": "2026-11-16T14:00:00Z"},
            ],
        },
        {
            "name": "antigravity",
            "label": "Antigravity",
            "rows": [
                {"group": "Gemini Models", "label": "Five Hour", "remaining": 10, "resets_at": "2026-11-09T15:00:00Z"},
            ],
        },
    ]

    # Threshold 20: 5-hour (15%) and Gemini Five Hour (10%)
    low = windows_below(limits, 20)
    assert len(low) == 2
    assert {w["label"] for w in low} == {"5-hour", "Five Hour"}

    # Threshold 12: only Gemini Five Hour (10%)
    low_strict = windows_below(limits, 12)
    assert len(low_strict) == 1
    assert low_strict[0]["label"] == "Five Hour"

    # Threshold 0 disables
    assert windows_below(limits, 0) == []


def test_alert_state_alerts_once_per_window(tmp_path):
    alerts_file = tmp_path / "alerts.json"
    state = AlertState(alerts_file)

    notified = []

    def mock_notify(title, body):
        notified.append({"title": title, "body": body})

    limits = [
        {
            "name": "claude",
            "label": "Claude Code",
            "rows": [
                {"group": "Claude Code", "label": "5-hour", "remaining": 10, "resets_at": "2026-11-09T14:00:00Z"},
            ],
        }
    ]

    # First check: triggers alert
    alerted = check_alerts(state, limits, 20, notify=mock_notify)
    assert len(alerted) == 1
    assert len(notified) == 1
    assert "Claude Code 5-hour: 10% left" in notified[0]["body"]

    # Second check same window: does NOT trigger alert again
    alerted2 = check_alerts(state, limits, 20, notify=mock_notify)
    assert len(alerted2) == 0
    assert len(notified) == 1

    # New window after reset: triggers alert again
    limits_next_cycle = [
        {
            "name": "claude",
            "label": "Claude Code",
            "rows": [
                {"group": "Claude Code", "label": "5-hour", "remaining": 15, "resets_at": "2026-11-09T19:00:00Z"},
            ],
        }
    ]
    alerted3 = check_alerts(state, limits_next_cycle, 20, notify=mock_notify)
    assert len(alerted3) == 1
    assert len(notified) == 2
    assert "Claude Code 5-hour: 15% left" in notified[1]["body"]
