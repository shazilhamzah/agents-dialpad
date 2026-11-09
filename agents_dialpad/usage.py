"""Usage logging and aggregation per agent/model."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path


class UsageLog:
    """<data>/usage-log.jsonl, one JSON object per finished reply. Lines older than 90 days are pruned at startup."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._prune_at_startup()

    def _prune_at_startup(self) -> None:
        if not self.path.exists():
            return
        now = time.time()
        cutoff = now - 90 * 86400
        kept = []
        changed = False
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("ts", 0) >= cutoff:
                        kept.append(line)
                    else:
                        changed = True
                except ValueError:
                    changed = True
            if changed:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
                os.replace(tmp, self.path)
        except OSError:
            pass

    def append(self, entry: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)

    def summary(self, days: int = 7, now: float | None = None) -> list[dict]:
        """[{"date": "YYYY-MM-DD" (local time), "provider", "replies", "input_tokens", "output_tokens", "errors"}], oldest first, missing days included with zeros."""
        now_dt = datetime.fromtimestamp(now) if now is not None else datetime.now()
        start_date = now_dt.date() - timedelta(days=days - 1)

        dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
        date_set = set(dates)

        # Read entries
        entries: list[dict] = []
        if self.path.exists():
            try:
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        continue
            except OSError:
                pass

        # Identify all relevant providers
        providers = {"claude", "antigravity", "codex"}
        for e in entries:
            p = e.get("provider")
            if p:
                providers.add(p)
        sorted_providers = sorted(providers)

        # Bucket by (date_str, provider)
        counts: dict[tuple[str, str], dict[str, int]] = {}
        for d in dates:
            for p in sorted_providers:
                counts[(d, p)] = {"replies": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0}

        for e in entries:
            ts = e.get("ts")
            if ts is None:
                continue
            e_date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            p = e.get("provider") or ""
            key = (e_date, p)
            if key in counts:
                bucket = counts[key]
                bucket["replies"] += 1
                bucket["input_tokens"] += int(e.get("input_tokens") or 0)
                bucket["output_tokens"] += int(e.get("output_tokens") or 0)
                if e.get("is_error"):
                    bucket["errors"] += 1

        out: list[dict] = []
        for d in dates:
            for p in sorted_providers:
                bucket = counts[(d, p)]
                out.append({
                    "date": d,
                    "provider": p,
                    "replies": bucket["replies"],
                    "input_tokens": bucket["input_tokens"],
                    "output_tokens": bucket["output_tokens"],
                    "errors": bucket["errors"],
                })
        return out
