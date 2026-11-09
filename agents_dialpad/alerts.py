"""Subscription rate-limit alerts."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def windows_below(limits: list[dict], threshold: int) -> list[dict]:
    """From the rows shown in the Limits sheet (provider, group, label, remaining, resets_at) return those with remaining < threshold."""
    if threshold <= 0:
        return []
    out = []
    for item in limits:
        if "rows" in item:
            p_name = item.get("name") or ""
            p_label = item.get("label") or p_name
            for row in item.get("rows") or []:
                rem = row.get("remaining")
                if rem is not None and rem < threshold:
                    out.append({
                        "provider": p_name,
                        "provider_label": p_label,
                        "group": row.get("group") or "",
                        "label": row.get("label") or "",
                        "remaining": rem,
                        "resets_at": row.get("resets_at"),
                    })
        elif "remaining" in item:
            rem = item.get("remaining")
            if rem is not None and rem < threshold:
                out.append({
                    "provider": item.get("provider") or item.get("name") or "",
                    "provider_label": item.get("provider_label") or item.get("label") or "",
                    "group": item.get("group") or "",
                    "label": item.get("label") or "",
                    "remaining": rem,
                    "resets_at": item.get("resets_at"),
                })
    return out


class AlertState:
    """<data>/alerts.json: which (provider, group, label, resets_at) were already alerted, so each window alerts once."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.alerted: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self.alerted = set(raw)
            elif isinstance(raw, dict) and "alerted" in raw:
                self.alerted = set(raw["alerted"])
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"alerted": sorted(self.alerted)}, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def key_for(item: dict) -> str:
        provider = item.get("provider") or ""
        group = item.get("group") or ""
        label = item.get("label") or ""
        resets = item.get("resets_at") or "no_reset"
        return f"{provider}:{group}:{label}:{resets}"

    def already_alerted(self, item: dict) -> bool:
        return self.key_for(item) in self.alerted

    def mark_alerted(self, item: dict) -> None:
        self.alerted.add(self.key_for(item))
        self._save()


def check_alerts(state: AlertState, limits_data: list[dict], threshold: int, notify=None) -> list[dict]:
    """Check limits and send notification for any new window below threshold."""
    low_windows = windows_below(limits_data, threshold)
    alerted = []
    for w in low_windows:
        if not state.already_alerted(w):
            state.mark_alerted(w)
            alerted.append(w)
            if notify:
                agent = w.get("provider_label") or w.get("provider") or "Agent"
                win = w.get("label") or "window"
                rem = w.get("remaining")
                title = "agents-dialpad"
                body = f"{agent} {win}: {rem}% left"
                try:
                    notify(title=title, body=body)
                except Exception:
                    pass
    return alerted
