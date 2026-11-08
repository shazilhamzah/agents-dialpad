"""Output parsers for the agent CLIs. Sample lines mirror real `stream-json` output."""
from agents_dialpad.providers import antigravity, claude


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
