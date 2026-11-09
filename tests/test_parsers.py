"""Output parsers for the agent CLIs. Sample lines mirror real `stream-json` output."""
import json
from pathlib import Path
from agents_dialpad.providers import antigravity, claude, codex

FIXTURES = Path(__file__).parent / "fixtures" / "codex"


def feed_all(parser, objs):
    out = []
    for o in objs:
        out += parser.feed(o)
    return out


# ---------------------------------------------------------------- Claude Code
def test_claude_streams_text_once():
    evs = feed_all(claude._Parser(), [
        {"type": "system", "subtype": "init", "session_id": "s1", "model": "m"},
        {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m1"}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "po"}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ng"}}},
        # the full assistant message repeats the text: it must not be emitted twice
        {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "pong"}]}},
    ])
    assert [e["type"] for e in evs] == ["session", "text", "text"]
    assert "".join(e.get("text", "") for e in evs) == "pong"
    assert evs[0]["session_id"] == "s1"


def test_claude_text_falls_back_to_assistant_message_when_no_deltas():
    evs = claude._Parser().feed({"type": "assistant", "message": {"id": "m9", "content": [{"type": "text", "text": "hi"}]}})
    assert evs == [{"type": "text", "text": "hi"}]


def test_claude_tool_use_and_result():
    p = claude._Parser()
    use = p.feed({"type": "assistant", "message": {"id": "m", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}})
    assert use == [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]
    res = p.feed({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "a\nb"}], "is_error": False}]}})
    assert res == [{"type": "tool_result", "id": "t1", "text": "a\nb", "is_error": False}]


def test_claude_long_tool_result_is_truncated():
    res = claude._Parser().feed({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t", "content": "x" * 10_000}]}})
    assert len(res[0]["text"]) < 4_100 and res[0]["text"].endswith("(truncated)")


def test_claude_ignores_subagent_chatter():
    p = claude._Parser()
    assert p.feed({"type": "assistant", "parent_tool_use_id": "t", "message": {"id": "x", "content": [{"type": "text", "text": "hi"}]}}) == []
    assert p.feed({"type": "stream_event", "parent_tool_use_id": "t", "event": {"type": "content_block_delta",
                   "delta": {"type": "text_delta", "text": "hi"}}}) == []


def test_claude_result_reports_denials_and_cost():
    (done,) = claude._Parser().feed({"type": "result", "is_error": False, "result": "ok", "total_cost_usd": 0.12,
                                     "duration_ms": 1500, "permission_denials": [{"tool_name": "Bash"}]})
    assert done["type"] == "done" and done["denials"] == ["Bash"] and done["cost_usd"] == 0.12


def test_claude_rate_limit_becomes_usage():
    (ev,) = claude._Parser().feed({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}})
    assert ev == {"type": "usage", "info": {"status": "allowed"}}


def test_claude_control_request_becomes_approval():
    p = claude._Parser()
    req = {
        "type": "control_request",
        "request_id": "req-123",
        "request": {
            "subtype": "can_use_tool",
            "tool_name": "PowerShell",
            "input": {"command": "dir"},
        },
    }
    (ev,) = p.feed(req)
    assert ev == {"type": "approval", "id": "req-123", "tool": "PowerShell", "input": {"command": "dir"}}


def test_claude_parses_recorded_control_fixtures():
    import json
    from pathlib import Path

    fixture_dir = Path(__file__).parent / "fixtures" / "claude_control"
    assert (fixture_dir / "allow_run.jsonl").exists()
    assert (fixture_dir / "deny_run.jsonl").exists()

    # Allow fixture
    p_allow = claude._Parser()
    allow_events = []
    with open(fixture_dir / "allow_run.jsonl", encoding="utf-8") as f:
        for line in f:
            allow_events += p_allow.feed(json.loads(line))
    event_types = [e["type"] for e in allow_events]
    assert "session" in event_types
    assert "approval" in event_types
    assert "done" in event_types
    appr = next(e for e in allow_events if e["type"] == "approval")
    assert appr["tool"] in ("PowerShell", "Bash")

    # Deny fixture
    p_deny = claude._Parser()
    deny_events = []
    with open(fixture_dir / "deny_run.jsonl", encoding="utf-8") as f:
        for line in f:
            deny_events += p_deny.feed(json.loads(line))
    deny_types = [e["type"] for e in deny_events]
    assert "session" in deny_types
    assert "approval" in deny_types
    assert "done" in deny_types
    done = next(e for e in deny_events if e["type"] == "done")
    assert len(done["denials"]) > 0


# ---------------------------------------------------------------- Antigravity
def test_agy_text_session_and_result():
    evs = feed_all(antigravity._Parser(), [
        {"event": "init", "conversation_id": "c1", "init": {"model": "gemini"}},
        {"event": "step_update", "step_update": {"step_type": "agent_response", "state": "ACTIVE", "text_delta": "stored."}},
        {"event": "result", "result": {"status": "SUCCESS", "response": "stored.\n", "duration_seconds": 2.5}},
    ])
    assert [e["type"] for e in evs] == ["session", "text", "done"]
    assert evs[0]["session_id"] == "c1"
    assert evs[-1]["is_error"] is False and evs[-1]["duration_ms"] == 2500


def test_agy_final_response_used_when_nothing_streamed():
    evs = antigravity._Parser().feed({"event": "result", "result": {"status": "SUCCESS", "response": "hello"}})
    assert [e["type"] for e in evs] == ["text", "done"] and evs[0]["text"] == "hello"


def test_agy_tool_steps_are_not_duplicated():
    p = antigravity._Parser()
    step = {"step_type": "tool", "tool_name": "run_command", "step_index": 2, "tool_info": {"parameters": {"CommandLine": "dir"}}}
    a = p.feed({"event": "step_update", "step_update": {**step, "state": "ACTIVE"}})
    b = p.feed({"event": "step_update", "step_update": {**step, "state": "DONE"}})
    assert [e["type"] for e in a] == ["tool_use"] and a[0]["input"] == {"CommandLine": "dir"}
    assert b == [{"type": "tool_result", "id": "2", "text": "", "is_error": False}]


def test_agy_denied_command_with_no_output_explains_why():
    p = antigravity._Parser()
    p.notes.append('jetski: no output produced — a tool required the "command" permission')
    evs = p.feed({"event": "result", "result": {"status": "SUCCESS", "response": "",
                                                "denied_actions": [{"action": "command", "display_name": "RunCommand"}]}})
    assert [e["type"] for e in evs] == ["error", "done"]
    assert "permission" in evs[0]["message"] and evs[1]["denials"] == ["RunCommand"]


def test_agy_failed_status_is_an_error():
    (done,) = antigravity._Parser().feed({"event": "result", "result": {"status": "FAILED", "response": ""}})
    assert done["is_error"] is True and done["result"] == "FAILED"


def test_agy_acp_recorded_fixtures():
    import json
    from pathlib import Path

    fixture_dir = Path(__file__).parent / "fixtures" / "agy_acp"
    assert (fixture_dir / "allow_run.jsonl").exists()
    assert (fixture_dir / "deny_run.jsonl").exists()
    assert (fixture_dir / "resume_run.jsonl").exists()

    def load_fixture(name):
        items = []
        with open(fixture_dir / name, encoding="utf-8") as f:
            for line in f:
                items.append(json.loads(line))
        return items

    # Allow run
    allow_msgs = load_fixture("allow_run.jsonl")
    perm_req = next(m["message"] for m in allow_msgs if m.get("message", {}).get("method") == "session/request_permission")
    assert perm_req["params"]["toolCall"]["name"] == "run_command"
    assert [o["optionId"] for o in perm_req["params"]["options"]] == ["allow", "deny"]
    allow_decision = next(m["message"] for m in allow_msgs if m.get("direction") == "send" and "result" in m.get("message", {}))
    assert allow_decision["result"]["outcome"]["optionId"] == "allow"

    # Deny run
    deny_msgs = load_fixture("deny_run.jsonl")
    deny_decision = next(m["message"] for m in deny_msgs if m.get("direction") == "send" and "result" in m.get("message", {}))
    assert deny_decision["result"]["outcome"]["optionId"] == "deny"
    failed_tool = next(
        m["message"] for m in deny_msgs
        if m.get("message", {}).get("method") == "session/update"
        and m["message"]["params"].get("update", {}).get("status") == "failed"
    )
    assert failed_tool["params"]["update"]["toolCallId"]

    # Resume run
    resume_msgs = load_fixture("resume_run.jsonl")
    load_req = next(m["message"] for m in resume_msgs if m.get("message", {}).get("method") == "session/load")
    assert load_req["params"]["sessionId"]
# ---------------------------------------------------------------- Codex
def _load_fixture(name: str) -> list[dict]:
    p = FIXTURES / name
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_codex_read_only_fixture():
    objs = _load_fixture("read_only_run.jsonl")
    evs = feed_all(codex._Parser(model="default"), objs)
    types = [e["type"] for e in evs]
    assert types == ["session", "text", "usage", "done"]
    assert evs[0]["session_id"].startswith("01a1bd")
    assert evs[1]["text"] == "pong"
    assert "input_tokens" in evs[2]["info"]
    assert evs[3]["is_error"] is False


def test_codex_command_fixture():
    objs = _load_fixture("command_run.jsonl")
    evs = feed_all(codex._Parser(model="default"), objs)
    types = [e["type"] for e in evs]
    assert "session" in types
    assert "tool_use" in types
    assert "tool_result" in types
    assert "text" in types
    assert "usage" in types
    assert types[-1] == "done"
    use = next(e for e in evs if e["type"] == "tool_use")
    assert use["name"] == "command_execution" and "echo hello" in use["input"]["command"]
    res = next(e for e in evs if e["type"] == "tool_result")
    assert res["is_error"] is False and "hello" in res["text"]
    assert evs[-1]["is_error"] is False


def test_codex_resume_fixture():
    objs = _load_fixture("resume_run.jsonl")
    evs = feed_all(codex._Parser(model="default"), objs)
    types = [e["type"] for e in evs]
    assert types == ["session", "text", "usage", "done"]
    assert evs[0]["session_id"].startswith("01a1bd")
    assert "echo hello" in evs[1]["text"]
    assert evs[-1]["is_error"] is False


def test_codex_error_fixture():
    objs = _load_fixture("error_run.jsonl")
    evs = feed_all(codex._Parser(model="invalid"), objs)
    types = [e["type"] for e in evs]
    assert types == ["session", "error", "done"]
    assert "invalid-model-xyz" in evs[1]["message"]
    assert evs[2]["is_error"] is True


def test_codex_long_tool_result_is_truncated():
    p = codex._Parser()
    p.feed({"type": "thread.started", "thread_id": "sid"})
    p.feed({
        "type": "item.started",
        "item": {"id": "c1", "type": "command_execution", "command": "cat big", "status": "in_progress"},
    })
    evs = p.feed({
        "type": "item.completed",
        "item": {"id": "c1", "type": "command_execution", "command": "cat big", "aggregated_output": "x" * 10_000, "exit_code": 0, "status": "completed"},
    })
    assert len(evs) == 1
    assert len(evs[0]["text"]) < 4_100 and evs[0]["text"].endswith("… (truncated)")

