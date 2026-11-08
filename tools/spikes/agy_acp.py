#!/usr/bin/env python3
"""Spike to test Antigravity ACP (Agent Client Protocol) over JSON-RPC 2.0 stdio.

Usage:
    python tools/spikes/agy_acp.py [--action allow|deny|prompt] [--prompt "..."] [--resume <session_id>] [--model <model_id>] [--save <file>]
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

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _anonymize(obj: any) -> any:
    """Recursively anonymize user names, personal paths, and dynamic IDs."""
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
    model: str | None = None,
    save_path: str | None = None,
    cwd: str | None = None,
    extra_cli_args: list[str] | None = None,
) -> tuple[list[dict], int, str, str | None]:
    exe = shutil.which(os.environ.get("AG_AGY", "agy"))
    if not exe:
        raise RuntimeError("agy executable not found on PATH.")

    target_dir = cwd or os.getcwd()
    args = [exe, "acp", *(extra_cli_args or [])]
    log(f"Spawning: {' '.join(args)} in {target_dir}")

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=target_dir,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    recorded_messages: list[dict] = []
    session_id: str | None = None
    next_rpc_id = 1
    prompt_rpc_id: int | None = None
    stop_reason: str | None = None

    async def send_rpc(msg: dict) -> None:
        nonlocal next_rpc_id
        recorded_messages.append({"direction": "send", "message": _anonymize(msg)})
        payload = json.dumps(msg) + "\n"
        proc.stdin.write(payload.encode("utf-8"))
        await proc.stdin.drain()

    # Read stderr asynchronously
    stderr_lines: list[str] = []

    async def drain_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                stderr_lines.append(text)
                log(f"STDERR: {text}")

    stderr_task = asyncio.create_task(drain_stderr())

    # Step 1: initialize
    init_id = next_rpc_id
    next_rpc_id += 1
    await send_rpc({
        "jsonrpc": "2.0",
        "id": init_id,
        "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "capabilities": {},
            "clientInfo": {
                "name": "dialtone-acp-spike",
                "version": "0.1.0",
            },
        },
    })

    # Step 2: session/new or session/load
    session_rpc_id = next_rpc_id
    next_rpc_id += 1
    if resume_id:
        log(f"Resuming session via session/load: {resume_id}")
        await send_rpc({
            "jsonrpc": "2.0",
            "id": session_rpc_id,
            "method": "session/load",
            "params": {
                "sessionId": resume_id,
                "cwd": target_dir.replace("\\", "/"),
                "mcpServers": [],
            },
        })
    else:
        log("Creating new session via session/new")
        await send_rpc({
            "jsonrpc": "2.0",
            "id": session_rpc_id,
            "method": "session/new",
            "params": {
                "cwd": target_dir.replace("\\", "/"),
                "mcpServers": [],
            },
        })

    # Event loop reading stdout
    while True:
        line_bytes = await proc.stdout.readline()
        if not line_bytes:
            log("EOF on stdout")
            break

        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log(f"Non-JSON line: {line}")
            continue

        recorded_messages.append({"direction": "recv", "message": _anonymize(msg)})

        # Check for response to session/new or session/load
        if msg.get("id") == session_rpc_id and "result" in msg:
            session_id = msg["result"].get("sessionId")
            log(f"Active sessionId: {session_id}")

            # Optional: configure model
            if model:
                model_rpc_id = next_rpc_id
                next_rpc_id += 1
                log(f"Setting model to: {model}")
                await send_rpc({
                    "jsonrpc": "2.0",
                    "id": model_rpc_id,
                    "method": "session/set_config_option",
                    "params": {
                        "sessionId": session_id,
                        "configId": "model",
                        "value": model,
                    },
                })

            # Send prompt
            prompt_rpc_id = next_rpc_id
            next_rpc_id += 1
            log(f"Sending prompt (id={prompt_rpc_id}): {prompt_text}")
            await send_rpc({
                "jsonrpc": "2.0",
                "id": prompt_rpc_id,
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "prompt": [
                        {
                            "type": "text",
                            "text": prompt_text,
                        }
                    ],
                },
            })
            continue

        # Check for permission request
        if msg.get("method") == "session/request_permission":
            req_id = msg.get("id")
            params = msg.get("params", {})
            tool_call = params.get("toolCall", {})
            tool_name = tool_call.get("name", "unknown")
            args_preview = tool_call.get("rawInput") or tool_call.get("args")
            options = params.get("options", [])
            log(f"PERMISSION REQUEST: id={req_id} tool={tool_name} args={args_preview}")
            log(f"Available options: {options}")

            chosen_option = "allow"
            if action == "prompt":
                resp = input("Allow this command? [y/N]: ").strip().lower()
                chosen_option = "allow" if resp in ("y", "yes") else "deny"
            elif action == "deny":
                chosen_option = "deny"
            else:
                chosen_option = "allow"

            log(f"Sending permission decision: {chosen_option}")
            await send_rpc({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": chosen_option,
                    }
                },
            })
            continue

        # Check for session updates
        if msg.get("method") == "session/update":
            update = msg.get("params", {}).get("update", {})
            u_type = update.get("sessionUpdate")
            if u_type == "agent_message_chunk":
                text = (update.get("content") or {}).get("text", "")
                log(f"TEXT CHUNK: {text!r}")
            elif u_type == "tool_call":
                log(f"TOOL CALL: {update.get('name')} (id={update.get('toolCallId')}, status={update.get('status')})")
            elif u_type == "tool_call_update":
                raw_out = update.get("rawOutput")
                status = update.get("status")
                log(f"TOOL UPDATE: id={update.get('toolCallId')} status={status} out={raw_out}")
            else:
                log(f"SESSION UPDATE: {u_type}")
            continue

        # Check for final prompt response
        if prompt_rpc_id is not None and msg.get("id") == prompt_rpc_id:
            result = msg.get("result", {})
            stop_reason = result.get("stopReason")
            usage = result.get("usage")
            log(f"PROMPT COMPLETED: stopReason={stop_reason} usage={usage}")
            # Done! Close stdin so process can exit cleanly
            log("Closing stdin to shut down ACP agent")
            proc.stdin.close()
            await proc.stdin.wait_closed()
            break

    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        log("Process did not exit after stdin close, terminating...")
        proc.terminate()
        await proc.wait()

    await stderr_task
    log(f"Process exited with code: {proc.returncode}")

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            for item in recorded_messages:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        log(f"Saved {len(recorded_messages)} messages to {save_path}")

    return recorded_messages, proc.returncode, session_id or "", stop_reason


def main():
    parser = argparse.ArgumentParser(description="Antigravity ACP protocol spike")
    parser.add_argument("--action", choices=["allow", "deny", "prompt"], default="allow", help="How to answer permission requests")
    parser.add_argument("--prompt", default="Run the shell command: echo hello", help="Prompt text to send")
    parser.add_argument("--resume", help="Resume an existing session ID using session/load")
    parser.add_argument("--model", help="Set model via session/set_config_option")
    parser.add_argument("--save", help="Path to save recorded JSON-RPC messages (JSONL)")
    parser.add_argument("--cwd", help="Working directory for the session")
    args = parser.parse_args()

    asyncio.run(
        run_spike(
            prompt_text=args.prompt,
            action=args.action,
            resume_id=args.resume,
            model=args.model,
            save_path=args.save,
            cwd=args.cwd,
        )
    )


if __name__ == "__main__":
    main()
