"""Quick commands: fixed, owner-defined one-tap commands."""
from __future__ import annotations

import asyncio
import shutil
import time

from .proc import kill_tree

MAX_OUTPUT = 50_000


def normalize(raw) -> tuple[dict[str, list[dict]], list[str]]:
    """Validate config["quick_commands"]. Returns (clean mapping, list of human-readable problems). Never raises."""
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, ["quick_commands must be a dictionary (mapping of project names to command lists)"]

    clean: dict[str, list[dict]] = {}
    problems: list[str] = []

    for proj, items in raw.items():
        if not isinstance(items, list):
            problems.append(f"quick_commands['{proj}'] must be a list")
            continue
        valid_items: list[dict] = []
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                problems.append(f"quick_commands['{proj}'][{i}] must be an object")
                continue
            label = it.get("label")
            if not isinstance(label, str) or not (1 <= len(label) <= 40):
                problems.append(f"quick_commands['{proj}'][{i}] label must be 1-40 characters")
                continue
            run_cmd = it.get("run")
            if not isinstance(run_cmd, list) or not run_cmd or not all(isinstance(x, str) and x for x in run_cmd):
                problems.append(f"quick_commands['{proj}'][{i}] ('{label}') run must be a non-empty list of strings")
                continue
            timeout = it.get("timeout", 120)
            if not isinstance(timeout, int) or isinstance(timeout, bool) or not (1 <= timeout <= 1800):
                problems.append(f"quick_commands['{proj}'][{i}] ('{label}') timeout must be an integer between 1 and 1800 seconds")
                continue
            valid_items.append({
                "label": label,
                "run": run_cmd,
                "timeout": timeout,
            })
        if valid_items:
            clean[proj] = valid_items

    return clean, problems


def commands_for(mapping: dict, project: str) -> list[dict]:
    """Global ('*') entries first, then the project's. Each item: {"index", "label", "run", "timeout"}."""
    all_cmds = []
    if "*" in mapping:
        all_cmds.extend(mapping["*"])
    if project != "*" and project in mapping:
        all_cmds.extend(mapping[project])

    return [
        {
            "index": idx,
            "label": c["label"],
            "run": c["run"],
            "timeout": c["timeout"],
        }
        for idx, c in enumerate(all_cmds)
    ]


async def run(argv: list[str], cwd: str, timeout: int) -> dict:
    """Returns {"exit_code", "timed_out", "output", "truncated", "duration_ms"}."""
    if not argv:
        raise FileNotFoundError("no command provided")
    exe = shutil.which(argv[0])
    if not exe:
        raise FileNotFoundError(argv[0])

    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(
        exe,
        *argv[1:],
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        timed_out = False
        exit_code = proc.returncode
    except asyncio.TimeoutError:
        timed_out = True
        exit_code = None
        kill_tree(proc.pid)
        try:
            out_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        except (asyncio.TimeoutError, Exception):
            out_bytes = b""

    duration_ms = round((time.time() - t0) * 1000)
    text = (out_bytes or b"").decode("utf-8", errors="replace")

    if len(text) > MAX_OUTPUT:
        text = "… output truncated, showing the last 50,000 characters\n" + text[-MAX_OUTPUT:]
        truncated = True
    else:
        truncated = False

    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "output": text,
        "truncated": truncated,
        "duration_ms": duration_ms,
    }
