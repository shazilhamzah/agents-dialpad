from __future__ import annotations

import json
from typing import Any

MAX_CHARS = 20_000
COMMAND_KEYS = ("command", "CommandLine", "cmd", "file_path", "path", "url", "pattern", "query")


def _cap_strings(obj: Any, limit: int = MAX_CHARS) -> tuple[Any, bool]:
    truncated = False
    if isinstance(obj, str):
        if len(obj) > limit:
            return obj[:limit], True
        return obj, False
    elif isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            new_v, cut = _cap_strings(v, limit)
            if cut:
                truncated = True
            new_dict[k] = new_v
        return new_dict, truncated
    elif isinstance(obj, list):
        new_list = []
        for item in obj:
            new_item, cut = _cap_strings(item, limit)
            if cut:
                truncated = True
            new_list.append(new_item)
        return new_list, truncated
    return obj, False


def approval_event(
    req_id: str,
    tool: str | None,
    raw_input: Any,
    description: str | None = "",
) -> dict:
    """Build a normalised approval event for any agent provider."""
    command = ""
    truncated = False

    if isinstance(raw_input, dict) and raw_input:
        for k in COMMAND_KEYS:
            val = raw_input.get(k)
            if val is not None and str(val).strip():
                command = str(val)
                break
        else:
            command = json.dumps(raw_input, ensure_ascii=False)
        safe_input, input_cut = _cap_strings(raw_input, MAX_CHARS)
        if input_cut:
            truncated = True
    elif raw_input:
        command = str(raw_input)
        safe_input = {}
    else:
        command = ""
        safe_input = {}

    if len(command) > MAX_CHARS:
        command = command[:MAX_CHARS]
        truncated = True

    return {
        "type": "approval",
        "id": str(req_id or ""),
        "tool": str(tool or ""),
        "command": command,
        "description": str(description or ""),
        "input": safe_input,
        "truncated": truncated,
    }
