"""A stand-in for the `claude` CLI that speaks its stream-json output. Used by the integration tests.

Behaviour is driven by words in the prompt: SLOW (emit for ~30s), TOOL (one tool call), DENY (report a blocked command).
Every invocation is appended to $FAKE_LOG as JSON so tests can assert on the exact flags the gateway passed.
"""
import json
import os
import sys
import time

args = sys.argv[1:]
prompt = sys.stdin.buffer.read().decode("utf-8")


def flag(name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def out(obj):
    sys.stdout.buffer.write((json.dumps(obj) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def delta(text):
    return {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}}


if os.environ.get("FAKE_LOG"):
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"agent": "claude", "argv": args, "prompt": prompt}) + "\n")

session = flag("--resume") or "claude-session-1"
out({"type": "system", "subtype": "init", "session_id": session, "model": flag("--model") or "default"})
out({"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m1"}}})

if "SLOW" in prompt:
    for i in range(300):
        out(delta(f"tick{i} "))
        time.sleep(0.1)

if "TOOL" in prompt:
    out({"type": "assistant", "message": {"id": "m0", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "echo hi"}}]}})
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "hi\n", "is_error": False}]}})

info = {"mode": flag("--permission-mode"), "model": flag("--model"), "resumed": "--resume" in args, "system": flag("--append-system-prompt")}
reply = "pong " + json.dumps(info, sort_keys=True)
out(delta(reply[:12]))
out(delta(reply[12:]))
out({"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": reply}]}})
soon = time.time() + 3600
out({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
    "five_hour": {"utilization": 0.25, "resetsAt": soon}, "seven_day": {"utilization": 0.5, "resetsAt": soon + 86400}}}})
out({"type": "result", "is_error": False, "result": reply, "total_cost_usd": 0.01, "duration_ms": 5,
     "permission_denials": [{"tool_name": "Bash"}] if "DENY" in prompt else [], "session_id": session})
