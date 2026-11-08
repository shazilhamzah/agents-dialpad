"""Shared helper: optional extra arguments placed right after an agent executable.

`AG_CLAUDE=/path/to/exe` picks the executable; `AG_CLAUDE_ARGS='["--flag", "value"]'` (a JSON list) adds arguments
after it. That is enough to wrap a CLI (for example `wsl claude`) and is how the test suite drives fake agents.
"""
from __future__ import annotations

import json
import os


def extra_args(var: str) -> list[str]:
    raw = os.environ.get(var)
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [str(v) for v in value] if isinstance(value, list) else []
