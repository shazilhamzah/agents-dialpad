"""A stand-in for the `codex` CLI that speaks its JSONL output. Used by the integration tests.

Handles `exec` and `exec resume [SESSION_ID]`.
Prompt words:
- SLOW: emit for ~30s with delay
- TOOL: emit command_execution item.started and item.completed (echo hi)
- DENY: emit command_execution with exit_code 1, status failed
"""
import json
import os
import sys
import time

args = sys.argv[1:]

if "login" in args and "status" in args:
    login_state = os.environ.get("FAKE_CODEX_LOGIN", "signed_in")
    if os.environ.get("FAKE_LOG"):
        with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"agent": "codex", "argv": args, "login": login_state}) + "\n")
    if login_state == "signed_out":
        sys.stdout.write("Not logged in\n")
        sys.exit(1)
    else:
        sys.stdout.write("Logged in using ChatGPT\n")
        sys.exit(0)

if "--version" in args:
    sys.stdout.write("codex-cli 0.164.0\n")
    sys.exit(0)

prompt = sys.stdin.buffer.read().decode("utf-8")


def flag(name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def out(obj):
    sys.stdout.buffer.write((json.dumps(obj) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


if os.environ.get("FAKE_LOG"):
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"agent": "codex", "argv": args, "prompt": prompt}) + "\n")

is_resume = "resume" in args
session_id = args[args.index("resume") + 1] if is_resume and args.index("resume") + 1 < len(args) else "codex-session-1"

out({"type": "thread.started", "thread_id": session_id})
out({"type": "turn.started"})

if "MODEL_NOT_ALLOWED" in prompt:
    err_json = json.dumps({
        "type": "error",
        "status": 400,
        "error": {
            "type": "invalid_request_error",
            "message": "The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.",
            "code": "model_not_found",
        },
    })
    out({"type": "error", "message": err_json})
    out({"type": "turn.failed", "error": {"message": err_json}})
    sys.exit(1)

if "SLOW" in prompt:
    for i in range(300):
        out({"type": "item.completed", "item": {"id": f"item_slow_{i}", "type": "agent_message", "text": f"tick{i} "}})
        time.sleep(0.1)

if "TOOL" in prompt:
    out({
        "type": "item.started",
        "item": {"id": "item_cmd_1", "type": "command_execution", "command": "echo hi", "aggregated_output": "", "exit_code": None, "status": "in_progress"},
    })
    out({
        "type": "item.completed",
        "item": {"id": "item_cmd_1", "type": "command_execution", "command": "echo hi", "aggregated_output": "hi\n", "exit_code": 0, "status": "completed"},
    })

if "DENY" in prompt:
    out({
        "type": "item.started",
        "item": {"id": "item_cmd_deny", "type": "command_execution", "command": "rm -rf /", "aggregated_output": "", "exit_code": None, "status": "in_progress"},
    })
    out({
        "type": "item.completed",
        "item": {"id": "item_cmd_deny", "type": "command_execution", "command": "rm -rf /", "aggregated_output": "Access denied\n", "exit_code": 1, "status": "failed"},
    })

info = {
    "mode": flag("-s"),
    "bypass": "--dangerously-bypass-approvals-and-sandbox" in args,
    "model": flag("-m"),
    "resumed": is_resume,
    "session_id": session_id,
    "cwd": flag("-C"),
}
reply = "codex " + json.dumps(info, sort_keys=True)
out({"type": "item.completed", "item": {"id": "item_msg_final", "type": "agent_message", "text": reply}})
out({
    "type": "turn.completed",
    "usage": {
        "input_tokens": 100,
        "cached_input_tokens": 50,
        "cache_write_input_tokens": 0,
        "output_tokens": 20,
        "reasoning_output_tokens": 5,
    },
})
