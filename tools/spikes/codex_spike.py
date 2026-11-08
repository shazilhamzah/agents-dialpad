#!/usr/bin/env python3
"""Spike to test Codex CLI execution and JSONL events protocol.

Usage:
    python tools/spikes/codex_spike.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys


def anonymize(text: str) -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "developer"
    text = text.replace(user, "developer")
    text = text.replace("MUHAMM~1", "developer")
    return text


def run_codex(
    args: list[str],
    prompt: str | None = None,
    cwd: str | None = None,
) -> tuple[int, list[str], str]:
    exe = shutil.which(os.environ.get("AG_CODEX", "codex"))
    if not exe:
        raise RuntimeError("codex executable not found on PATH.")

    cmd = [exe, *args]
    print(f"Running: {' '.join(cmd)}")
    p = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=cwd,
    )
    lines = [anonymize(line.strip()) for line in p.stdout.splitlines() if line.strip()]
    stderr = anonymize(p.stderr)
    return p.returncode, lines, stderr


def save_fixture(path: str, lines: list[str]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    print(f"Saved {len(lines)} lines to {path}")


def main():
    print("=== Codex Spike ===")
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    scratch_dir = os.path.join(repo_root, "scratch", "codex_spike_temp")
    os.makedirs(scratch_dir, exist_ok=True)

    try:
        # 1. Read-only turn (pong)
        code1, lines1, err1 = run_codex(
            ["exec", "--json", "--skip-git-repo-check", "-C", scratch_dir, "-s", "read-only", "-m", "gpt-5.6-terra", "-"],
            prompt="Reply with exactly: pong",
        )
        print(f"Step 1 code: {code1}, lines: {len(lines1)}")
        if err1:
            print(f"Step 1 stderr: {err1.strip()}")
        save_fixture(os.path.join(repo_root, "tests", "fixtures", "codex", "read_only_run.jsonl"), lines1)

        # 2. Command execution turn (echo hello)
        code2, lines2, err2 = run_codex(
            ["exec", "--json", "--skip-git-repo-check", "-C", scratch_dir, "-s", "workspace-write", "-m", "gpt-5.6-terra", "-"],
            prompt="run echo hello and tell me the output",
        )
        print(f"Step 2 code: {code2}, lines: {len(lines2)}")
        if err2:
            print(f"Step 2 stderr: {err2.strip()}")
        save_fixture(os.path.join(repo_root, "tests", "fixtures", "codex", "command_run.jsonl"), lines2)

        session_id = None
        for line in lines2:
            try:
                data = json.loads(line)
                if data.get("type") == "thread.started":
                    session_id = data.get("thread_id")
                    break
            except Exception:
                pass
        print(f"Extracted session id: {session_id}")

        # 3. Resume session
        if session_id:
            code3, lines3, err3 = run_codex(
                ["exec", "--json", "--skip-git-repo-check", "-m", "gpt-5.6-terra", "resume", session_id, "-"],
                prompt="what did I ask before?",
            )
            print(f"Step 3 code: {code3}, lines: {len(lines3)}")
            if err3:
                print(f"Step 3 stderr: {err3.strip()}")
            save_fixture(os.path.join(repo_root, "tests", "fixtures", "codex", "resume_run.jsonl"), lines3)

        # 4. Error turn (invalid model)
        code4, lines4, err4 = run_codex(
            ["exec", "--json", "--skip-git-repo-check", "-C", scratch_dir, "-s", "read-only", "-m", "invalid-model-xyz", "-"],
            prompt="Hello",
        )
        print(f"Step 4 code: {code4}, lines: {len(lines4)}")
        if err4:
            print(f"Step 4 stderr: {err4.strip()}")
        save_fixture(os.path.join(repo_root, "tests", "fixtures", "codex", "error_run.jsonl"), lines4)

    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    print("=== All Spike Fixtures Recorded ===")


if __name__ == "__main__":
    main()
