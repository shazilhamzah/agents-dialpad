"""A stand-in for the Antigravity `agy` CLI. Used by the integration tests.

Handles: `models`, `-p=/usage`, and prompts (-p=<text>) with `--output-format stream-json`.
Prompt words: SLOW (emit for ~30s), TOOL (one tool step), DENY (a command denied, no output).
"""
import json
import os
import sys
import time

args = sys.argv[1:]


def flag(name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def out(obj):
    sys.stdout.buffer.write((json.dumps(obj) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


if args and args[-1] == "models":
    print("gemini-test-low\tGemini Test (Low)\ngemini-test-high\tGemini Test (High)")
    sys.exit(0)

prompt = next((a[3:] for a in args if a.startswith("-p=")), "")

if prompt == "/usage":
    print("Gemini Models\tWeekly Limit Remaining\t81%\t2026-11-14T10:28:58Z\n"
          "Gemini Models\tFive Hour Limit Remaining\t100%\t2026-11-08T21:40:16Z")
    sys.exit(0)

if os.environ.get("FAKE_LOG"):
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"agent": "agy", "argv": args, "prompt": prompt}) + "\n")

conv = flag("--conversation") or "agy-conv-1"
out({"event": "init", "conversation_id": conv, "init": {"model": flag("--model") or "default"}})


def step(**kw):
    out({"event": "step_update", "step_update": {"conversation_id": conv, **kw}})


if "SLOW" in prompt:
    for i in range(300):
        step(step_index=1, state="ACTIVE", step_type="agent_response", text_delta=f"tick{i} ")
        time.sleep(0.1)

if "TOOL" in prompt or "DENY" in prompt:
    step(step_index=2, state="ACTIVE", step_type="tool", tool_name="run_command", tool_info={"parameters": {"CommandLine": "echo hi"}})
    step(step_index=2, state="ERROR" if "DENY" in prompt else "DONE", step_type="tool", tool_name="run_command",
         tool_info={"parameters": {"CommandLine": "echo hi"}})

if "DENY" in prompt:
    print('jetski: no output produced - a tool required the "command" permission that headless mode cannot prompt for', flush=True)
    out({"event": "result", "result": {"conversation_id": conv, "status": "SUCCESS", "response": "", "duration_seconds": 1.5,
                                       "denied_actions": [{"action": "command", "display_name": "RunCommand"}]}})
    sys.exit(0)

info = {"mode": flag("--mode"), "model": flag("--model"), "resumed": "--conversation" in args,
        "skip_permissions": "--dangerously-skip-permissions" in args, "saw_prompt": prompt[:40]}
reply = "agy " + json.dumps(info, sort_keys=True)
step(step_index=3, state="ACTIVE", step_type="agent_response", text_delta=reply[:10])
step(step_index=3, state="DONE", step_type="agent_response", text_delta=reply[10:])
out({"event": "result", "result": {"conversation_id": conv, "status": "SUCCESS", "response": reply, "duration_seconds": 0.5}})
