"""Provider registry. Add a new CLI by writing a class with the same shape as ClaudeProvider."""
from __future__ import annotations

from .antigravity import AntigravityProvider
from .claude import ClaudeProvider

PROVIDERS = {p.name: p for p in (ClaudeProvider(), AntigravityProvider())}

# Shown greyed-out in the UI until they are implemented.
PLANNED = [
    {"name": "codex", "label": "Codex"},
]
