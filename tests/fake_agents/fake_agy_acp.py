"""A stand-in for `agy acp` speaking Agent Client Protocol (ACP) JSON-RPC 2.0.

Used by the integration tests for Antigravity approvals.
"""
from __future__ import annotations

import json
import os
import sys
import time


def out(obj: dict) -> None:
    sys.stdout.buffer.write((json.dumps(obj) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def run(args: list[str]) -> None:
    session_id = "agy-session-1"
    model = ""

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params") or {}

        if method == "initialize":
            out({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": 1,
                    "agentCapabilities": {"loadSession": True, "load_session": True},
                    "agentInfo": {"name": "Fake Antigravity ACP", "version": "1.0.0"},
                },
            })

        elif method in ("session/new", "session/load"):
            if params.get("sessionId"):
                session_id = params["sessionId"]
            out({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "sessionId": session_id,
                    "models": {
                        "availableModels": [{"modelId": "gemini-test-low", "name": "Gemini Test"}],
                        "currentModelId": model or "gemini-test-low",
                    },
                    "modes": {
                        "currentModeId": "default",
                        "availableModes": [
                            {"id": "default", "name": "Default"},
                            {"id": "accept-edits", "name": "Accept edits"},
                            {"id": "plan", "name": "Plan"},
                        ],
                    },
                    "configOptions": [],
                },
            })

        elif method == "session/set_config_option":
            if params.get("configId") == "model":
                model = params.get("value", "")
            out({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"configOptions": []},
            })

        elif method == "session/prompt":
            prompt_list = params.get("prompt") or []
            prompt_text = "".join(p.get("text", "") for p in prompt_list if isinstance(p, dict))

            if os.environ.get("FAKE_LOG"):
                with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"agent": "agy", "argv": args, "prompt": prompt_text}) + "\n")

            if "SLOW" in prompt_text:
                for i in range(300):
                    out({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": f"tick{i} "},
                            },
                        },
                    })
                    time.sleep(0.1)
                out({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"stopReason": "end_turn"},
                })

            elif "NEEDS_APPROVAL" in prompt_text:
                call_id = "call_1"
                req_perm_id = "req-1"

                # 1. tool_call
                out({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": call_id,
                            "name": "run_command",
                            "args": {"CommandLine": "echo hi", "WaitMsBeforeAsync": 5000, "toolSummary": "Run echo hi"},
                            "status": "pending",
                            "kind": "execute",
                            "title": "echo hi",
                            "rawInput": {"CommandLine": "echo hi", "WaitMsBeforeAsync": 5000, "toolSummary": "Run echo hi"},
                        },
                    },
                })

                # 2. session/request_permission
                out({
                    "jsonrpc": "2.0",
                    "id": req_perm_id,
                    "method": "session/request_permission",
                    "params": {
                        "sessionId": session_id,
                        "toolCall": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": call_id,
                            "name": "run_command",
                            "args": {"CommandLine": "echo hi", "WaitMsBeforeAsync": 5000, "toolSummary": "Run echo hi"},
                            "status": "pending",
                            "kind": "execute",
                            "title": "echo hi",
                            "rawInput": {"CommandLine": "echo hi", "WaitMsBeforeAsync": 5000, "toolSummary": "Run echo hi"},
                        },
                        "options": [
                            {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                            {"optionId": "deny", "name": "Deny", "kind": "reject_once"},
                        ],
                    },
                })

                # Read permission decision response
                resp_line = sys.stdin.readline()
                allow = False
                if resp_line:
                    try:
                        decision_msg = json.loads(resp_line)
                        outcome = decision_msg.get("result", {}).get("outcome", {})
                        allow = (outcome.get("optionId") == "allow")
                    except Exception:
                        pass

                if allow:
                    out({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "tool_call_update",
                                "toolCallId": call_id,
                                "status": "completed",
                                "rawOutput": {"output": "hi\n", "exit_code": 0},
                                "content": [{"type": "content", "content": {"type": "text", "text": "hi\n"}}],
                            },
                        },
                    })
                    reply = "pong approved"
                    out({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": reply},
                            },
                        },
                    })
                    out({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"stopReason": "end_turn"},
                    })
                else:
                    out({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "tool_call_update",
                                "toolCallId": call_id,
                                "status": "failed",
                                "rawOutput": {"output": ""},
                                "content": [{"type": "content", "content": {"type": "text", "text": ""}}],
                            },
                        },
                    })
                    reply = "pong denied"
                    out({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": reply},
                            },
                        },
                    })
                    out({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"stopReason": "end_turn"},
                    })

            else:
                info = {"mode": "default", "model": model, "resumed": params.get("sessionId") == session_id}
                reply = "pong " + json.dumps(info, sort_keys=True)
                out({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": reply},
                        },
                    },
                })
                out({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"stopReason": "end_turn"},
                })


if __name__ == "__main__":
    run(sys.argv[1:])
