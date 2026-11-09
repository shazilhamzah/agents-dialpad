#!/usr/bin/env python3
"""Spike to test Claude Code permission control protocol over stdin/stdout.

Usage:
    python tools/spikes/claude_control.py [--action allow|deny|prompt] [--prompt "..."] [--resume <id>] [--save <file>]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time

if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _anonymize(obj: any) -> any:
    """Recursively anonymize user names / personal paths."""
    if isinstance(obj, str):
        cleaned = obj
        user = os.environ.get("USERNAME") or os.environ.get("USER")
        if user:
            cleaned = cleaned.replace(user, "developer")
        cleaned = cleaned.replace("MUHAMM~1", "developer")
        return cleaned
    if isinstance(obj, list):
        return [_anonymize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _anonymize(v) for k, v in obj.items()}
    return obj


def log(msg: str) -> None:
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


async def run_spike(
    prompt_text: str,
    action: str = "allow",
    resume_id: str | None = None,
    save_path: str | None = None,
    permission_mode: str = "manual",
    permission_prompts: str = "host",
    cwd: str | None = None,
    extra_cli_args: list[str] | None = None,
) -> tuple[list[dict], int, str, str | None]:
    exe = shutil.which(os.environ.get("AG_CLAUDE", "claude"))
    if not exe:
        raise RuntimeError("claude executable not found on PATH.")

    temp_created = False
    if cwd is None:
        temp_dir = tempfile.mkdtemp(prefix="claude-control-spike-")
        temp_created = True
    else:
        temp_dir = cwd
        os.makedirs(temp_dir, exist_ok=True)

    log(f"Working dir: {temp_dir}")
    recorded_frames: list[dict] = []

    cmd = [
        exe,
        "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", permission_mode,
        "--permission-prompts", permission_prompts,
        "--permission-prompt-tool", "stdio",
    ]
    if resume_id:
        cmd += ["--resume", resume_id]
    if extra_cli_args:
        cmd += extra_cli_args

    log(f"Starting: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=temp_dir,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1 << 25,
    )

    async def log_stderr():
        assert proc.stderr is not None
        while line := await proc.stderr.readline():
            log(f"[stderr] {line.decode('utf-8', 'replace').rstrip()}")

    stderr_task = asyncio.create_task(log_stderr())

    # Write initial user prompt frame
    user_frame = {
        "type": "user",
        "message": {
            "role": "user",
            "content": prompt_text,
        },
    }
    user_line = json.dumps(user_frame) + "\n"
    log(f"[stdin >] {user_line.strip()}")
    assert proc.stdin is not None
    proc.stdin.write(user_line.encode("utf-8"))
    await proc.stdin.drain()

    assert proc.stdout is not None
    session_id = None
    saw_result = False

    try:
        while line := await proc.stdout.readline():
            raw = line.decode("utf-8", "replace").strip()
            if not raw:
                continue
            log(f"[stdout <] {raw}")
            try:
                frame = json.loads(raw)
            except Exception as e:
                log(f"[parse err] {e}: {raw}")
                continue

            recorded_frames.append(frame)

            t = frame.get("type")
            if t == "system" and frame.get("subtype") == "init":
                session_id = frame.get("session_id")
                log(f"-> Captured session_id: {session_id}")

            elif t == "control_request":
                req_id = frame.get("request_id")
                req = frame.get("request") or {}
                subtype = req.get("subtype")
                log(f"-> Received control_request: id={req_id}, subtype={subtype}")

                if subtype == "can_use_tool":
                    tool_name = req.get("tool_name")
                    tool_input = req.get("input")
                    log(f"-> Tool request: {tool_name} with input: {tool_input}")

                    # Decide allow or deny
                    if action == "allow":
                        response_payload = {
                            "type": "control_response",
                            "response": {
                                "subtype": "success",
                                "request_id": req_id,
                                "response": {
                                    "behavior": "allow",
                                    "updatedInput": tool_input,
                                },
                            },
                        }
                    elif action == "deny":
                        response_payload = {
                            "type": "control_response",
                            "response": {
                                "subtype": "success",
                                "request_id": req_id,
                                "response": {
                                    "behavior": "deny",
                                    "message": "The user denied this",
                                },
                            },
                        }
                    else:
                        log(f"Unknown action {action}, defaulting to deny")
                        response_payload = {
                            "type": "control_response",
                            "response": {
                                "subtype": "success",
                                "request_id": req_id,
                                "response": {
                                    "behavior": "deny",
                                    "message": "User denied",
                                },
                            },
                        }

                    resp_line = json.dumps(response_payload) + "\n"
                    log(f"[stdin >] {resp_line.strip()}")
                    proc.stdin.write(resp_line.encode("utf-8"))
                    await proc.stdin.drain()

                else:
                    log(f"-> Unhandled control_request subtype: {subtype}")

            elif t == "result":
                log(f"-> Received result frame! is_error={frame.get('is_error')}")
                saw_result = True
                # Let's see if process closes itself or if closing stdin is required
                log("-> Will wait 2 seconds to see if process exits on its own...")
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                    log(f"-> Process exited on its own with code {proc.returncode}!")
                    break
                except asyncio.TimeoutError:
                    log("-> Process did not exit after result; closing stdin now...")
                    proc.stdin.close()
                    await proc.stdin.wait_closed()
                    code = await proc.wait()
                    log(f"-> Process exited after closing stdin with code {code}.")
                    break

        ret = await proc.wait()
        await stderr_task
    finally:
        if temp_created and not resume_id:
            pass  # keep directory or delete if not needed

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            for f_obj in recorded_frames:
                clean_obj = _anonymize(f_obj)
                f.write(json.dumps(clean_obj) + "\n")
        log(f"Saved {len(recorded_frames)} frames to {save_path}")

    return recorded_frames, ret, temp_dir, session_id


def main():
    parser = argparse.ArgumentParser(description="Spike Claude Code control protocol")
    parser.add_argument("--action", choices=["allow", "deny"], default="allow")
    parser.add_argument("--prompt", default="Run a powershell command to write text to foo.txt")
    parser.add_argument("--resume", default=None)
    parser.add_argument("--save", default=None)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--mode", default="manual")
    args = parser.parse_args()

    asyncio.run(
        run_spike(
            prompt_text=args.prompt,
            action=args.action,
            resume_id=args.resume,
            save_path=args.save,
            permission_mode=args.mode,
            cwd=args.cwd,
        )
    )


if __name__ == "__main__":
    main()
