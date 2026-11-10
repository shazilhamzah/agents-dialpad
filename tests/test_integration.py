"""End-to-end tests: the real FastAPI app, real subprocesses, with fake `claude` / `agy` CLIs (no subscriptions needed)."""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents_dialpad import config, pairing, push
from agents_dialpad.app import create_app
from agents_dialpad.keepawake import KeepAwake
from agents_dialpad.providers import antigravity, codex

FAKES = Path(__file__).parent / "fake_agents"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fresh data dir with both fake agents wired in. Returns a function that builds a client with config overrides."""
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.delenv("AG_TOKEN", raising=False)
    monkeypatch.setenv("AG_CLAUDE", sys.executable)
    monkeypatch.setenv("AG_CLAUDE_ARGS", json.dumps([str(FAKES / "fake_claude.py")]))
    monkeypatch.setenv("AG_AGY", sys.executable)
    monkeypatch.setenv("AG_AGY_ARGS", json.dumps([str(FAKES / "fake_agy.py")]))
    monkeypatch.setenv("AG_CODEX", sys.executable)
    monkeypatch.setenv("AG_CODEX_ARGS", json.dumps([str(FAKES / "fake_codex.py")]))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(antigravity, "_models_cache", None)
    monkeypatch.setattr(antigravity, "_limits_cache", None)
    monkeypatch.setattr(codex, "_status_cache", (time.time(), {"state": "ready", "note": ""}))
    (tmp_path / "ws").mkdir()
    base = {"projects": {"workspace": str(tmp_path / "ws")}}

    def make(keep_awake=None, **extra):
        (tmp_path / "config.json").write_text(json.dumps({**base, **extra}), encoding="utf-8")
        cfg, token = config.load()
        return TestClient(create_app(cfg, token, keep_awake=keep_awake)), {"Authorization": "Bearer " + token}

    return make


@pytest.fixture
def calls(tmp_path):
    def read():
        p = tmp_path / "calls.jsonl"
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
    return read


def new_chat(client, h, provider="claude", mode="readonly", model=""):
    r = client.post("/api/chats", headers=h, json={"provider": provider, "project": "workspace", "mode": mode, "model": model})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def turn(client, h, chat_id, text):
    """Send a message, then read the replayed stream to the end. Returns the list of events."""
    assert client.post(f"/api/chats/{chat_id}/messages", headers=h, json={"text": text}).status_code == 202
    with client.stream("GET", f"/api/chats/{chat_id}/stream?start=0", headers=h) as r:
        return [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]


def text_of(events):
    return "".join(e.get("text", "") for e in events if e["type"] == "text")


def reply_info(events):
    return json.loads(text_of(events).split(" ", 1)[1])


def wait_until_idle(client, h, chat_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if not client.get(f"/api/chats/{chat_id}", headers=h).json()["running"]:
            return
        time.sleep(0.1)
    raise AssertionError("run did not finish")


# --------------------------------------------------------------------------- basics
def test_api_needs_the_token_but_the_ui_does_not(env):
    with env()[0] as client:
        assert client.get("/api/info").status_code == 401
        assert client.get("/api/info", headers={"Authorization": "Bearer nope"}).status_code == 401
        page = client.get("/")
        assert page.status_code == 200 and "markdown.js" in page.text      # static files ship inside the package


def test_info_lists_agents_models_projects_and_modes(env):
    client, h = env()
    with client:
        info = client.get("/api/info", headers=h).json()
        agents = {p["name"]: p for p in info["providers"]}
        assert agents["claude"]["available"] and agents["antigravity"]["available"] and agents["codex"]["available"]
        assert [m["id"] for m in agents["codex"]["models"]] == [""]
        assert [m["id"] for m in agents["antigravity"]["models"]][:2] == ["", "gemini-test-low"]
        assert info["projects"] == ["workspace"]
        assert [m["id"] for m in info["modes"]] == ["readonly", "edit", "ask"]       # no full access unless enabled
        assert [m["id"] for m in agents["claude"]["modes"]] == ["readonly", "edit", "ask"]
        assert [m["id"] for m in agents["antigravity"]["modes"]] == ["readonly", "edit", "ask"]


# --------------------------------------------------------------------------- claude
def test_claude_turn_streams_persists_and_names_the_chat(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        events = turn(client, h, cid, "hello there")
        assert [e["type"] for e in events][0] == "session" and events[-1]["type"] == "done"
        assert text_of(events).startswith("pong ")
        wait_until_idle(client, h, cid)
        chat = client.get(f"/api/chats/{cid}", headers=h).json()
        assert chat["title"] == "hello there" and chat["session_id"] == "claude-session-1"
        assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
        assert chat["messages"][1]["events"][-1]["type"] == "done"


def test_second_message_resumes_the_session(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        first = reply_info(turn(client, h, cid, "one"))
        wait_until_idle(client, h, cid)
        second = reply_info(turn(client, h, cid, "two"))
        assert first["resumed"] is False and second["resumed"] is True
        assert "--resume" in calls()[1]["argv"] and calls()[1]["argv"][calls()[1]["argv"].index("--resume") + 1] == "claude-session-1"


def test_mode_model_and_instructions_reach_the_cli(env, calls, tmp_path):
    (tmp_path / "style.md").write_text("Answer tersely.", encoding="utf-8")
    client, h = env(instructions_file=str(tmp_path / "style.md"))
    with client:
        cid = new_chat(client, h, mode="edit", model="claude-haiku-5-5")
        info = reply_info(turn(client, h, cid, "x"))
        assert info == {"mode": "acceptEdits", "model": "claude-haiku-5-5", "resumed": False, "system": "Answer tersely."}
        assert calls()[0]["prompt"] == "x"                                    # the prompt itself is untouched


def test_readonly_is_the_default_and_maps_to_plan(env):
    client, h = env()
    with client:
        assert reply_info(turn(client, h, new_chat(client, h), "x"))["mode"] == "plan"


def test_model_can_change_between_messages(env):
    client, h = env()
    with client:
        cid = new_chat(client, h, model="claude-haiku-5-5")
        turn(client, h, cid, "a")
        wait_until_idle(client, h, cid)
        assert client.patch(f"/api/chats/{cid}", headers=h, json={"model": "claude-sonnet-5-5"}).json() == {"model": "claude-sonnet-5-5"}
        assert reply_info(turn(client, h, cid, "b"))["model"] == "claude-sonnet-5-5"


def test_tool_calls_and_blocked_commands_are_reported(env):
    client, h = env()
    with client:
        events = turn(client, h, new_chat(client, h), "TOOL DENY")
        kinds = [e["type"] for e in events]
        assert "tool_use" in kinds and "tool_result" in kinds
        assert next(e for e in events if e["type"] == "tool_result")["text"] == "hi\n"
        assert next(e for e in events if e["type"] == "done")["denials"] == ["Bash"]


def test_usage_from_the_reply_feeds_the_limits_view(env):
    client, h = env()
    with client:
        turn(client, h, new_chat(client, h), "x")
        limits = {p["name"]: p for p in client.get("/api/limits", headers=h).json()["providers"]}
        rows = {r["label"]: r["remaining"] for r in limits["claude"]["rows"]}
        assert rows == {"5-hour": 75, "Weekly": 50}
        assert {r["label"] for r in limits["antigravity"]["rows"]} == {"Weekly", "Five Hour"}   # parsed from `agy -p=/usage`


# --------------------------------------------------------------------------- antigravity
def test_antigravity_turn_and_conversation_resume(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="antigravity", mode="edit", model="gemini-test-low")
        first = turn(client, h, cid, "hi")
        info = json.loads(text_of(first).split(" ", 1)[1])
        assert info["mode"] == "accept-edits" and info["model"] == "gemini-test-low" and info["resumed"] is False
        assert info["skip_permissions"] is False
        wait_until_idle(client, h, cid)
        assert reply_info_agy(turn(client, h, cid, "again"))["resumed"] is True
        assert "--conversation" in calls()[1]["argv"]


def reply_info_agy(events):
    return json.loads(text_of(events).split(" ", 1)[1])


def test_antigravity_denied_command_explains_itself(env):
    client, h = env()
    with client:
        events = turn(client, h, new_chat(client, h, provider="antigravity"), "DENY")
        kinds = [e["type"] for e in events]
        assert "error" in kinds and "permission" in next(e for e in events if e["type"] == "error")["message"]
        assert next(e for e in events if e["type"] == "done")["denials"] == ["RunCommand"]
        assert next(e for e in events if e["type"] == "tool_result")["is_error"] is True


def test_antigravity_gets_instructions_prefixed_to_the_prompt(env, tmp_path, calls):
    (tmp_path / "style.md").write_text("Be brief.", encoding="utf-8")
    client, h = env(instructions_file=str(tmp_path / "style.md"))
    with client:
        turn(client, h, new_chat(client, h, provider="antigravity"), "question")
        prompt = calls()[0]["prompt"]
        assert prompt.startswith("Be brief.") and prompt.endswith("question")


# --------------------------------------------------------------------------- codex
def test_codex_turn_and_resume(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="codex", mode="edit", model="o3-mini")
        first = turn(client, h, cid, "hello")
        info = json.loads(text_of(first).split(" ", 1)[1])
        assert info["mode"] == "workspace-write" and info["model"] == "o3-mini" and info["resumed"] is False
        assert info["bypass"] is False
        wait_until_idle(client, h, cid)
        chat = client.get(f"/api/chats/{cid}", headers=h).json()
        assert chat["session_id"] == "codex-session-1"

        second = turn(client, h, cid, "again")
        info2 = json.loads(text_of(second).split(" ", 1)[1])
        assert info2["resumed"] is True and info2["session_id"] == "codex-session-1"
        argv = calls()[1]["argv"]
        assert "resume" in argv and argv[argv.index("resume") + 1] == "codex-session-1"


def test_codex_modes_map_to_sandbox_flags(env, calls):
    client, h = env()
    with client:
        # readonly
        cid1 = new_chat(client, h, provider="codex", mode="readonly")
        turn(client, h, cid1, "x")
        argv1 = calls()[0]["argv"]
        assert "-s" in argv1 and argv1[argv1.index("-s") + 1] == "read-only"

        # edit
        cid2 = new_chat(client, h, provider="codex", mode="edit")
        turn(client, h, cid2, "y")
        argv2 = calls()[1]["argv"]
        assert "-s" in argv2 and argv2[argv2.index("-s") + 1] == "workspace-write"


def test_codex_full_access_needs_the_flag(env, calls):
    client, h = env(allow_full_access=False)
    with client:
        r = client.post("/api/chats", headers=h, json={"provider": "codex", "project": "workspace", "mode": "full"})
        assert r.status_code == 400

    client, h = env(allow_full_access=True)
    with client:
        cid = new_chat(client, h, provider="codex", mode="full")
        turn(client, h, cid, "z")
        argv = calls()[0]["argv"]
        assert "--dangerously-bypass-approvals-and-sandbox" in argv
        assert "-s" not in argv


def test_codex_stop(env):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="codex")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "SLOW"})
        time.sleep(1.5)
        assert client.get(f"/api/chats/{cid}", headers=h).json()["running"] is True
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert events[-1] == {"type": "done", "is_error": False, "stopped": True}
        assert "tick0" in text_of(events)


def test_codex_gets_instructions_prefixed(env, tmp_path, calls):
    (tmp_path / "style.md").write_text("Terse caveman.", encoding="utf-8")
    client, h = env(instructions_file=str(tmp_path / "style.md"))
    with client:
        turn(client, h, new_chat(client, h, provider="codex"), "question")
        prompt = calls()[0]["prompt"]
        assert prompt.startswith("Terse caveman.") and prompt.endswith("question")



# --------------------------------------------------------------------------- permissions
def test_full_access_only_exists_when_enabled(env, calls):
    client, h = env()
    with client:
        r = client.post("/api/chats", headers=h, json={"provider": "claude", "project": "workspace", "mode": "full"})
        assert r.status_code == 400
    client, h = env(allow_full_access=True)
    with client:
        assert "full" in [m["id"] for m in client.get("/api/info", headers=h).json()["modes"]]
        assert reply_info(turn(client, h, new_chat(client, h, mode="full"), "x"))["mode"] == "bypassPermissions"
        info = reply_info_agy(turn(client, h, new_chat(client, h, provider="antigravity", mode="full"), "x"))
        assert info["skip_permissions"] is True


def test_full_access_chats_drop_to_edit_when_the_flag_is_turned_off(env):
    client, h = env(allow_full_access=True)
    with client:
        cid = new_chat(client, h, mode="full")
    client, h = env(allow_full_access=False)
    with client:
        assert reply_info(turn(client, h, cid, "x"))["mode"] == "acceptEdits"


# --------------------------------------------------------------------------- validation
def test_bad_input_is_rejected(env):
    client, h = env()
    with client:
        post = lambda **kw: client.post("/api/chats", headers=h, json={"provider": "claude", "project": "workspace", **kw}).status_code
        assert post(model="--dangerously-skip-permissions") == 400     # would be parsed as a flag
        assert post(model="gpt-9") == 400
        assert post(mode="nope") == 400
        assert client.post("/api/chats", headers=h, json={"provider": "claude", "project": "../etc"}).status_code == 400
        assert client.post("/api/chats", headers=h, json={"provider": "unknown", "project": "workspace"}).status_code == 400
        assert client.post("/api/chats", headers=h, json={"provider": "antigravity", "project": "workspace", "mode": "ask"}).status_code == 200
        assert client.get("/api/chats/..%5C..%5Cconfig", headers=h).status_code == 404


# --------------------------------------------------------------------------- approvals
def test_ask_mode_waits_and_runs_after_allow(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and not calls():
            time.sleep(0.05)
        end = time.time() + 5
        approved = False
        while time.time() < end:
            r = client.post(f"/api/chats/{cid}/approvals/req-1", headers=h, json={"allow": True})
            if r.status_code == 200:
                assert r.json() == {"ok": True}
                approved = True
                break
            time.sleep(0.05)
        assert approved, "Approval request req-1 was not received in time"
        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert "pong approved" in text_of(events)
        assert any(e.get("type") == "approval" and (e.get("id") == "req-1" or e.get("req_id") == "req-1") for e in events)
        assert any(e.get("type") == "approval_result" and e.get("allow") is True and e.get("by") == "user" for e in events)
        chat = client.get(f"/api/chats/{cid}", headers=h).json()
        saved_appr = next(
            ev
            for msg in chat.get("messages", [])
            for ev in msg.get("events", [])
            if ev.get("type") == "approval"
        )
        assert saved_appr["command"] == "echo hi"


def test_ask_mode_continues_after_deny(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and not calls():
            time.sleep(0.05)
        end = time.time() + 5
        denied = False
        while time.time() < end:
            r = client.post(f"/api/chats/{cid}/approvals/req-1", headers=h, json={"allow": False})
            if r.status_code == 200:
                assert r.json() == {"ok": True}
                denied = True
                break
            time.sleep(0.05)
        assert denied, "Approval request req-1 was not received in time"
        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert "pong denied" in text_of(events)
        assert any(e.get("type") == "approval" and (e.get("id") == "req-1" or e.get("req_id") == "req-1") for e in events)
        assert any(e.get("type") == "approval_result" and e.get("allow") is False and e.get("by") == "user" for e in events)


def test_unanswered_approval_times_out_as_deny(env, monkeypatch):
    monkeypatch.setenv("AG_APPROVAL_TIMEOUT", "1")
    client, h = env()
    with client:
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        wait_until_idle(client, h, cid, timeout=10)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert "pong denied" in text_of(events)
        assert any(e.get("type") == "approval_result" and e.get("allow") is False and e.get("by") == "timeout" for e in events)


def test_stopping_while_waiting_ends_the_reply(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and not calls():
            time.sleep(0.05)
        time.sleep(0.3)
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert events[-1] == {"type": "done", "is_error": False, "stopped": True}
        assert any(e.get("type") == "approval_result" and e.get("by") == "stopped" for e in events)


def test_approving_twice_is_409_and_unknown_is_404(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and not calls():
            time.sleep(0.05)
        # Unknown req id returns 404
        assert client.post(f"/api/chats/{cid}/approvals/req-unknown", headers=h, json={"allow": True}).status_code == 404
        # Wait until req-1 is pending
        end = time.time() + 5
        approved = False
        while time.time() < end:
            r = client.post(f"/api/chats/{cid}/approvals/req-1", headers=h, json={"allow": True})
            if r.status_code == 200:
                approved = True
                break
            time.sleep(0.05)
        assert approved, "Approval request req-1 was not received in time"
        # Second decision on the same req returns 409
        assert client.post(f"/api/chats/{cid}/approvals/req-1", headers=h, json={"allow": True}).status_code == 409
        wait_until_idle(client, h, cid)


def test_approval_route_needs_the_token(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and not calls():
            time.sleep(0.05)
        # Missing auth header -> 401
        assert client.post(f"/api/chats/{cid}/approvals/req-1", json={"allow": True}).status_code == 401
        # Bad auth header -> 401
        assert client.post(f"/api/chats/{cid}/approvals/req-1", headers={"Authorization": "Bearer wrong"}, json={"allow": True}).status_code == 401
        # Valid auth header -> wait until pending and approve
        end = time.time() + 5
        approved = False
        while time.time() < end:
            r = client.post(f"/api/chats/{cid}/approvals/req-1", headers=h, json={"allow": True})
            if r.status_code == 200:
                approved = True
                break
            time.sleep(0.05)
        assert approved, "Approval request req-1 was not received in time"
        wait_until_idle(client, h, cid)


def test_other_modes_are_unchanged(env, calls):
    client, h = env()
    with client:
        # readonly mode
        cid_ro = new_chat(client, h, mode="readonly")
        turn(client, h, cid_ro, "test readonly")
        wait_until_idle(client, h, cid_ro)
        ro_call = calls()[-1]
        assert "--input-format" not in ro_call["argv"]
        assert "--permission-prompts" not in ro_call["argv"]
        assert "--permission-prompt-tool" not in ro_call["argv"]
        assert ro_call["prompt"] == "test readonly"

        # edit mode
        cid_edit = new_chat(client, h, mode="edit")
        turn(client, h, cid_edit, "test edit")
        wait_until_idle(client, h, cid_edit)
        edit_call = calls()[-1]
        assert "--input-format" not in edit_call["argv"]
        assert "--permission-prompts" not in edit_call["argv"]
        assert "--permission-prompt-tool" not in edit_call["argv"]
        assert edit_call["prompt"] == "test edit"

        # ask mode: verifies it does include --input-format stream-json and permission flags
        cid_ask = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid_ask}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and len(calls()) < 3:
            time.sleep(0.05)
        ask_call = calls()[-1]
        assert "--input-format" in ask_call["argv"] and ask_call["argv"][ask_call["argv"].index("--input-format") + 1] == "stream-json"
        assert "--permission-prompts" in ask_call["argv"] and ask_call["argv"][ask_call["argv"].index("--permission-prompts") + 1] == "host"
        assert "--permission-prompt-tool" in ask_call["argv"] and ask_call["argv"][ask_call["argv"].index("--permission-prompt-tool") + 1] == "stdio"
        # Finish the run
        client.post(f"/api/chats/{cid_ask}/approvals/req-1", headers=h, json={"allow": True})
        wait_until_idle(client, h, cid_ask)


def test_agy_ask_mode_waits_and_runs_after_allow(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="antigravity", mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and not calls():
            time.sleep(0.05)
        end = time.time() + 5
        approved = False
        while time.time() < end:
            r = client.post(f"/api/chats/{cid}/approvals/req-1", headers=h, json={"allow": True})
            if r.status_code == 200:
                assert r.json() == {"ok": True}
                approved = True
                break
            time.sleep(0.05)
        assert approved, "Approval request req-1 was not received in time"
        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert "pong approved" in text_of(events)
        assert any(e.get("type") == "approval" and (e.get("id") == "req-1" or e.get("req_id") == "req-1") for e in events)
        assert any(e.get("type") == "approval_result" and e.get("allow") is True and e.get("by") == "user" for e in events)
        chat = client.get(f"/api/chats/{cid}", headers=h).json()
        saved_appr = next(
            ev
            for msg in chat.get("messages", [])
            for ev in msg.get("events", [])
            if ev.get("type") == "approval"
        )
        assert saved_appr["command"] == "echo hi"


def test_agy_ask_mode_continues_after_deny(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="antigravity", mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and not calls():
            time.sleep(0.05)
        end = time.time() + 5
        denied = False
        while time.time() < end:
            r = client.post(f"/api/chats/{cid}/approvals/req-1", headers=h, json={"allow": False})
            if r.status_code == 200:
                assert r.json() == {"ok": True}
                denied = True
                break
            time.sleep(0.05)
        assert denied, "Approval request req-1 was not received in time"
        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert "pong denied" in text_of(events)
        assert any(e.get("type") == "approval" and (e.get("id") == "req-1" or e.get("req_id") == "req-1") for e in events)
        assert any(e.get("type") == "approval_result" and e.get("allow") is False and e.get("by") == "user" for e in events)


def test_agy_unanswered_approval_times_out_as_deny(env, monkeypatch):
    monkeypatch.setenv("AG_APPROVAL_TIMEOUT", "1")
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="antigravity", mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        wait_until_idle(client, h, cid, timeout=10)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert "pong denied" in text_of(events)
        assert any(e.get("type") == "approval_result" and e.get("allow") is False and e.get("by") == "timeout" for e in events)


def test_agy_stopping_while_waiting_ends_the_reply(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="antigravity", mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})
        end = time.time() + 5
        while time.time() < end and not calls():
            time.sleep(0.05)
        time.sleep(0.3)
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert events[-1] == {"type": "done", "is_error": False, "stopped": True}
        assert any(e.get("type") == "approval_result" and e.get("by") == "stopped" for e in events)


def test_agy_second_message_resumes_session_in_ask_mode(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="antigravity", mode="ask")
        turn(client, h, cid, "first")
        wait_until_idle(client, h, cid)
        turn(client, h, cid, "second")
        wait_until_idle(client, h, cid)
        call_list = [c for c in calls() if c.get("agent") == "agy"]
        assert len(call_list) >= 2
        chat = client.get(f"/api/chats/{cid}", headers=h).json()
        assert chat["session_id"] == "agy-session-1"


def test_agy_other_modes_use_dash_p(env, calls):
    client, h = env()
    with client:
        # readonly
        cid_ro = new_chat(client, h, provider="antigravity", mode="readonly")
        turn(client, h, cid_ro, "ro")
        wait_until_idle(client, h, cid_ro)
        last_call = calls()[-1]
        assert "acp" not in last_call["argv"]
        assert any(a.startswith("-p=") for a in last_call["argv"])

        # edit
        cid_edit = new_chat(client, h, provider="antigravity", mode="edit")
        turn(client, h, cid_edit, "edit")
        wait_until_idle(client, h, cid_edit)
        last_call = calls()[-1]
        assert "acp" not in last_call["argv"]
        assert any(a.startswith("-p=") for a in last_call["argv"])

        # ask
        cid_ask = new_chat(client, h, provider="antigravity", mode="ask")
        turn(client, h, cid_ask, "ask")
        wait_until_idle(client, h, cid_ask)
        last_call = calls()[-1]
        assert "acp" in last_call["argv"]
        assert not any(a.startswith("-p=") for a in last_call["argv"])


# --------------------------------------------------------------------------- run control
def test_stop_ends_a_running_reply(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "SLOW"})
        time.sleep(1.5)
        assert client.get(f"/api/chats/{cid}", headers=h).json()["running"] is True
        assert client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "again"}).status_code == 409
        assert client.patch(f"/api/chats/{cid}", headers=h, json={"model": "claude-haiku-5-5"}).status_code == 409
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as r:
            events = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert events[-1] == {"type": "done", "is_error": False, "stopped": True}
        assert "tick0" in text_of(events)                              # what arrived before the stop is kept


def test_stream_can_be_replayed_from_an_offset(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        full = turn(client, h, cid, "x")
        with client.stream("GET", f"/api/chats/{cid}/stream?start=2", headers=h) as r:
            tail = [json.loads(line) for line in r.iter_lines() if line and '"ping"' not in line]
        assert tail == full[2:]


def test_deleting_a_running_chat_does_not_bring_it_back(env, tmp_path):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "SLOW"})
        time.sleep(1)
        assert client.delete(f"/api/chats/{cid}", headers=h).status_code == 200
        time.sleep(2)                                                  # the killed run finishes and must not re-save the chat
        assert client.get(f"/api/chats/{cid}", headers=h).status_code == 404
        assert not (tmp_path / "chats" / f"{cid}.json").exists()


def test_chats_survive_a_restart(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        turn(client, h, cid, "remember me")
        wait_until_idle(client, h, cid)
    client, h = env()                                                  # a brand-new app on the same data folder
    with client:
        chats = client.get("/api/chats", headers=h).json()["chats"]
        assert [c["id"] for c in chats] == [cid] and chats[0]["title"] == "remember me"
        assert client.get(f"/api/chats/{cid}", headers=h).json()["messages"][0]["text"] == "remember me"


# --------------------------------------------------------------------------- keep awake
class _FakeKeepAwakeBackend:
    def __init__(self):
        self.calls: list[str] = []

    def on(self) -> None:
        self.calls.append("on")

    def off(self) -> None:
        self.calls.append("off")


def test_computer_stays_awake_only_while_a_reply_runs(env):
    backend = _FakeKeepAwakeBackend()
    client, h = env(keep_awake=KeepAwake(enabled=True, backend=backend))
    with client:
        cid = new_chat(client, h)
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "SLOW"})
        time.sleep(1)
        assert backend.calls == ["on"]
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)
        assert backend.calls == ["on", "off"]


def test_keep_awake_survives_a_failing_agent(env, monkeypatch, tmp_path):
    backend = _FakeKeepAwakeBackend()
    client, h = env(keep_awake=KeepAwake(enabled=True, backend=backend))
    with client:
        cid = new_chat(client, h)
        monkeypatch.setenv("AG_CLAUDE", str(tmp_path / "nope"))
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "x"})
        wait_until_idle(client, h, cid)
        assert backend.calls[-1] == "off"


# --------------------------------------------------------------------------- pairing
def test_pair_endpoint_returns_a_qr_and_needs_the_token(env, monkeypatch):
    monkeypatch.setattr(pairing, "tailscale_url", lambda port: None)
    client, h = env()
    with client:
        assert client.get("/api/pair").status_code == 401
        r = client.get("/api/pair", headers=h)
        assert r.status_code == 200
        data = r.json()
        assert data["qr"].startswith("data:image/svg+xml")
        assert "#token=" in data["url"]
        assert data["remote"] is False


# --------------------------------------------------------------------------- chat housekeeping (A3)
def test_renaming_while_a_reply_runs_is_not_lost(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "SLOW"})
        time.sleep(1)
        r = client.patch(f"/api/chats/{cid}", headers=h, json={"title": "Renamed"})
        assert r.status_code == 200
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)
        chat = client.get(f"/api/chats/{cid}", headers=h).json()
        assert chat["title"] == "Renamed"
        assert len(chat["messages"]) >= 2
        assert chat["messages"][-1]["role"] == "assistant"


def test_rename_validates_the_title(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        assert client.patch(f"/api/chats/{cid}", headers=h, json={"title": ""}).status_code == 400
        assert client.patch(f"/api/chats/{cid}", headers=h, json={"title": "   "}).status_code == 400
        assert client.patch(f"/api/chats/{cid}", headers=h, json={"title": "a" * 81}).status_code in (400, 422)
        r = client.patch(f"/api/chats/{cid}", headers=h, json={"title": "Valid Title"})
        assert r.status_code == 200
        assert r.json()["title"] == "Valid Title"


def test_model_change_is_still_refused_while_running(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "SLOW"})
        time.sleep(1)
        r = client.patch(f"/api/chats/{cid}", headers=h, json={"model": "claude-haiku-5-5"})
        assert r.status_code == 409
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)


def test_pinned_chats_come_first(env):
    client, h = env()
    with client:
        a = new_chat(client, h)
        time.sleep(0.05)
        b = new_chat(client, h)
        time.sleep(0.05)
        c = new_chat(client, h)
        chats = client.get("/api/chats", headers=h).json()["chats"]
        assert [x["id"] for x in chats[:3]] == [c, b, a]
        client.patch(f"/api/chats/{a}", headers=h, json={"pinned": True})
        chats_after = client.get("/api/chats", headers=h).json()["chats"]
        assert chats_after[0]["id"] == a
        assert chats_after[0]["pinned"] is True


def test_search_finds_titles_and_message_text(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        turn(client, h, cid, "ping pong test")
        wait_until_idle(client, h, cid)
        res = client.get("/api/chats?q=pong", headers=h).json()["chats"]
        assert len(res) == 1
        assert res[0]["id"] == cid
        assert "snippet" in res[0]
        assert "pong" in res[0]["snippet"].lower()
        res_empty = client.get("/api/chats?q=zzznonexistent", headers=h).json()["chats"]
        assert res_empty == []


def test_export_returns_markdown_with_the_conversation(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        turn(client, h, cid, "hello export")
        wait_until_idle(client, h, cid)
        r = client.get(f"/api/chats/{cid}/export", headers=h)
        assert r.status_code == 200
        cd = r.headers.get("content-disposition", "")
        assert cd.endswith('.md"') or ".md" in cd
        body = r.text
        assert body.startswith("# ")
        assert "## You" in body
        assert "hello export" in body


# --------------------------------------------------------------------------- quick commands (A4)
def test_quick_commands_list_and_run(env):
    cfg_cmd = {"*": [{"label": "Hi", "run": [sys.executable, "-c", "print(42)"]}]}
    client, h = env(quick_commands=cfg_cmd)
    with client:
        cmds = client.get("/api/projects/workspace/commands", headers=h).json()
        assert len(cmds) == 1
        assert cmds[0]["label"] == "Hi"
        assert cmds[0]["index"] == 0
        r = client.post("/api/projects/workspace/commands/0", headers=h)
        assert r.status_code == 200
        res = r.json()
        assert res["exit_code"] == 0
        assert "42" in res["output"]


def test_unknown_project_or_index_is_404(env):
    cfg_cmd = {"*": [{"label": "Hi", "run": [sys.executable, "-c", "print(42)"]}]}
    client, h = env(quick_commands=cfg_cmd)
    with client:
        assert client.get("/api/projects/unknown_proj/commands", headers=h).status_code == 404
        assert client.post("/api/projects/unknown_proj/commands/0", headers=h).status_code == 404
        assert client.post("/api/projects/workspace/commands/99", headers=h).status_code == 404


def test_quick_commands_need_the_token(env):
    client, _ = env()
    with client:
        assert client.get("/api/projects/workspace/commands").status_code == 401
        assert client.post("/api/projects/workspace/commands/0").status_code == 401




# --------------------------------------------------------------------------- push notifications (B1)
def test_push_routes_need_the_token(env):
    client, _ = env()
    with client:
        assert client.get("/api/push/key").status_code == 401
        assert client.post("/api/push/subscribe", json={"subscription": {}}).status_code == 401
        assert client.post("/api/push/unsubscribe", json={"endpoint": "https://example.com"}).status_code == 401
        assert client.post("/api/push/test").status_code == 401


def test_subscribe_validates_and_stores(env):
    client, h = env()
    with client:
        # Invalid subscription
        r = client.post("/api/push/subscribe", headers=h, json={"subscription": {"endpoint": "bad"}})
        assert r.status_code == 400

        # Valid subscription
        sub = {
            "endpoint": "https://push.example.com/phone1",
            "keys": {"p256dh": "key1", "auth": "auth1"},
        }
        r = client.post("/api/push/subscribe", headers=h, json={"subscription": sub, "label": "pixel"})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        # Unsubscribe
        r = client.post("/api/push/unsubscribe", headers=h, json={"endpoint": "https://push.example.com/phone1"})
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_a_finished_reply_triggers_a_notification(env, monkeypatch):
    sent_payloads = []

    def fake_send_all(subs, payload, data_dir, contact):
        sent_payloads.append(payload)
        return len(subs.all())

    from agents_dialpad import push
    monkeypatch.setattr(push, "send_all", fake_send_all)

    client, h = env()
    with client:
        sub = {
            "endpoint": "https://push.example.com/phone1",
            "keys": {"p256dh": "key1", "auth": "auth1"},
        }
        client.post("/api/push/subscribe", headers=h, json={"subscription": sub, "label": "phone"})

        cid = new_chat(client, h)
        turn(client, h, cid, "ping")
        wait_until_idle(client, h, cid)

        time.sleep(0.1)

        assert len(sent_payloads) == 1
        assert sent_payloads[0]["tag"] == cid
        assert sent_payloads[0]["url"] == f"/#/c/{cid}"
        assert sent_payloads[0]["body"] == "Your reply is ready"


def test_stopped_replies_do_not_notify(env, monkeypatch):
    sent_payloads = []

    def fake_send_all(subs, payload, data_dir, contact):
        sent_payloads.append(payload)
        return len(subs.all())

    from agents_dialpad import push
    monkeypatch.setattr(push, "send_all", fake_send_all)

    client, h = env()
    with client:
        sub = {
            "endpoint": "https://push.example.com/phone1",
            "keys": {"p256dh": "key1", "auth": "auth1"},
        }
        client.post("/api/push/subscribe", headers=h, json={"subscription": sub, "label": "phone"})

        cid = new_chat(client, h)
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "SLOW"})
        time.sleep(1.5)
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)
        time.sleep(0.1)

        assert len(sent_payloads) == 0


def test_key_route_returns_501_without_pywebpush(env, monkeypatch):
    from agents_dialpad import push

    def fake_key(data_dir):
        raise push.PushUnavailable("pywebpush is not installed")

    monkeypatch.setattr(push, "vapid_public_key", fake_key)

    client, h = env()
    with client:
        r = client.get("/api/push/key", headers=h)
        assert r.status_code == 501
        assert "pywebpush is not installed" in r.text


# --------------------------------------------------------------------------- change viewer (B2)
def test_changes_routes_need_the_token_and_a_known_project(env):
    client, h = env()
    with client:
        # 401 without token
        assert client.get("/api/projects/workspace/changes").status_code == 401
        assert client.get("/api/projects/workspace/changes/diff?path=file.txt").status_code == 401
        assert client.post("/api/projects/workspace/changes/revert", json={"path": "file.txt"}).status_code == 401

        # 404 for unknown project
        assert client.get("/api/projects/unknown_proj/changes", headers=h).status_code == 404
        assert client.get("/api/projects/unknown_proj/changes/diff?path=file.txt", headers=h).status_code == 404
        assert client.post("/api/projects/unknown_proj/changes/revert", headers=h, json={"path": "file.txt"}).status_code == 404


def test_revert_is_refused_while_an_agent_runs_in_that_project(env, tmp_path):
    import subprocess
    ws = tmp_path / "ws"
    subprocess.run(["git", "-C", str(ws), "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(ws), "-c", "user.name=T", "-c", "user.email=t@e", "commit", "--allow-empty", "-m", "init"], capture_output=True, check=True)
    (ws / "hello.txt").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(ws), "add", "hello.txt"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(ws), "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-m", "add hello"], capture_output=True, check=True)

    # Modify file
    (ws / "hello.txt").write_text("modified\n", encoding="utf-8")

    client, h = env()
    with client:
        cid = new_chat(client, h)
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "SLOW"})
        time.sleep(1.5)

        # Revert is refused while agent is running
        r = client.post("/api/projects/workspace/changes/revert", headers=h, json={"path": "hello.txt"})
        assert r.status_code == 409
        assert "An agent is working in this project" in r.text

        # Stop turn and wait
        client.post(f"/api/chats/{cid}/stop", headers=h)
        wait_until_idle(client, h, cid)

        # Now revert succeeds
        r2 = client.post("/api/projects/workspace/changes/revert", headers=h, json={"path": "hello.txt"})
        assert r2.status_code == 200
        assert r2.json() == {"ok": True}
        assert (ws / "hello.txt").read_text(encoding="utf-8") == "original\n"


# --------------------------------------------------------------------------- desk sessions (B3)
def test_import_creates_a_chat_that_resumes_the_session(env, calls, tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude_home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    ws_dir = str(tmp_path / "ws")

    sid = "77777777-7777-7777-7777-777777777777"
    proj_folder = claude_dir / "projects" / "workspace"
    proj_folder.mkdir(parents=True, exist_ok=True)
    p = proj_folder / f"{sid}.jsonl"
    p.write_text(
        json.dumps({"type": "user", "cwd": ws_dir, "message": "My previous desk question"}) + "\n",
        encoding="utf-8",
    )

    client, h = env()
    with client:
        # Check sessions list endpoint
        sessions = client.get("/api/projects/workspace/desk-sessions", headers=h).json()
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid
        assert sessions[0]["preview"] == "My previous desk question"

        # Import
        r = client.post(
            "/api/chats/import",
            headers=h,
            json={"project": "workspace", "session_id": sid, "mode": "readonly"},
        )
        assert r.status_code == 200
        chat = r.json()
        assert chat["session_id"] == sid
        assert chat["imported"] is True
        assert chat["title"] == "My previous desk question"

        # Now send a message in this imported chat: fake claude gets --resume <id>
        turn(client, h, chat["id"], "what was the word?")
        wait_until_idle(client, h, chat["id"])

        last_call = calls()[-1]
        assert "--resume" in last_call["argv"]
        assert last_call["argv"][last_call["argv"].index("--resume") + 1] == sid


def test_import_rejects_unknown_or_foreign_sessions(env, tmp_path, monkeypatch):
    claude_dir = tmp_path / "claude_home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    client, h = env()
    with client:
        # Unknown session id (belongs_to is False)
        sid = "88888888-8888-8888-8888-888888888888"
        r = client.post(
            "/api/chats/import",
            headers=h,
            json={"project": "workspace", "session_id": sid, "mode": "readonly"},
        )
        assert r.status_code == 404
        assert "That desktop session was not found" in r.text

        # Unknown project
        r = client.post(
            "/api/chats/import",
            headers=h,
            json={"project": "unknown_proj", "session_id": sid, "mode": "readonly"},
        )
        assert r.status_code == 400

        # Invalid mode
        r = client.post(
            "/api/chats/import",
            headers=h,
            json={"project": "workspace", "session_id": sid, "mode": "invalid_mode"},
        )
        assert r.status_code == 400


def test_desk_sessions_need_the_token(env):
    client, _ = env()
    with client:
        assert client.get("/api/projects/workspace/desk-sessions").status_code == 401
        assert client.post("/api/chats/import", json={"project": "workspace", "session_id": "00000000-0000-0000-0000-000000000000"}).status_code == 401


# --------------------------------------------------------------------------- uploads (B4)
def test_upload_then_send_gives_the_agent_access(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="claude")

        # Upload a file
        r = client.put(
            f"/api/chats/{cid}/uploads?name=error.log",
            headers={**h, "Content-Type": "text/plain"},
            content=b"FATAL: crash dump\n",
        )
        assert r.status_code == 200
        stored = r.json()
        assert stored["name"].endswith("-error.log")

        # Send message with attachment
        r_msg = client.post(
            f"/api/chats/{cid}/messages",
            headers=h,
            json={"text": "check this crash", "attachments": [stored["name"]]},
        )
        assert r_msg.status_code == 202
        wait_until_idle(client, h, cid)

        last_call = calls()[-1]
        assert "--add-dir" in last_call["argv"]
        add_dir_idx = last_call["argv"].index("--add-dir")
        dir_arg = last_call["argv"][add_dir_idx + 1]
        assert cid in dir_arg

        prompt = last_call["prompt"]
        assert "check this crash" in prompt
        assert "Attached files (read them from these paths):" in prompt
        assert stored["name"] in prompt


def test_upload_limits(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)

        # 415 on bad type
        r_bad = client.put(
            f"/api/chats/{cid}/uploads?name=malware.exe",
            headers={**h, "Content-Type": "application/octet-stream"},
            content=b"bad content",
        )
        assert r_bad.status_code == 415

        # 413 on declared too large
        r_decl = client.put(
            f"/api/chats/{cid}/uploads?name=big.txt",
            headers={**h, "Content-Length": str(20 * 1024 * 1024), "Content-Type": "text/plain"},
            content=b"pretend big",
        )
        assert r_decl.status_code == 413


def test_attachments_must_belong_to_the_chat(env):
    client, h = env()
    with client:
        cid1 = new_chat(client, h)
        cid2 = new_chat(client, h)

        r = client.put(
            f"/api/chats/{cid1}/uploads?name=note.txt",
            headers={**h, "Content-Type": "text/plain"},
            content=b"hello",
        )
        stored_name = r.json()["name"]

        # cid2 attempts to use cid1's attachment
        r_foreign = client.post(
            f"/api/chats/{cid2}/messages",
            headers=h,
            json={"text": "use foreign file", "attachments": [stored_name]},
        )
        assert r_foreign.status_code == 400


def test_deleting_a_chat_removes_its_uploads(env, tmp_path):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        r = client.put(
            f"/api/chats/{cid}/uploads?name=test.txt",
            headers={**h, "Content-Type": "text/plain"},
            content=b"data",
        )
        assert r.status_code == 200

        udir = tmp_path / "uploads" / cid
        assert udir.exists()

        client.delete(f"/api/chats/{cid}", headers=h)
        assert not udir.exists()


def test_antigravity_also_gets_the_folder(env, calls):
    client, h = env()
    with client:
        cid = new_chat(client, h, provider="antigravity")
        r = client.put(
            f"/api/chats/{cid}/uploads?name=spec.md",
            headers={**h, "Content-Type": "text/markdown"},
            content=b"# Spec",
        )
        stored = r.json()

        client.post(
            f"/api/chats/{cid}/messages",
            headers=h,
            json={"text": "look at spec", "attachments": [stored["name"]]},
        )
        wait_until_idle(client, h, cid)

        last_call = calls()[-1]
        assert "--add-dir" in last_call["argv"]
        add_dir_idx = last_call["argv"].index("--add-dir")
        dir_arg = last_call["argv"][add_dir_idx + 1]
        assert cid in dir_arg


def test_upload_needs_the_token(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
    assert client.put(f"/api/chats/{cid}/uploads?name=test.txt", content=b"unauth").status_code == 401


# --------------------------------------------------------------------------- device tokens (B5)
def test_device_token_can_use_the_api(env):
    client, h_owner = env()
    with client:
        # Owner adds a device
        r = client.post("/api/devices", headers=h_owner, json={"name": "Pixel 9"})
        assert r.status_code == 200
        data = r.json()
        dev_id = data["device"]["id"]
        # Extract token from the pair URL (#token=...)
        url = data["url"]
        dev_token = url.split("#token=")[1]

        h_dev = {"Authorization": f"Bearer {dev_token}"}

        # Device token can list chats and create chat
        assert client.get("/api/chats", headers=h_dev).status_code == 200
        cid = new_chat(client, h_dev)
        assert client.get(f"/api/chats/{cid}", headers=h_dev).status_code == 200


def test_revoked_device_token_is_rejected(env):
    client, h_owner = env()
    with client:
        r = client.post("/api/devices", headers=h_owner, json={"name": "iPad"})
        data = r.json()
        dev_id = data["device"]["id"]
        dev_token = data["url"].split("#token=")[1]
        h_dev = {"Authorization": f"Bearer {dev_token}"}

        assert client.get("/api/chats", headers=h_dev).status_code == 200

        # Owner revokes device
        r_del = client.delete(f"/api/devices/{dev_id}", headers=h_owner)
        assert r_del.status_code == 200

        # Device token is now rejected immediately (401)
        assert client.get("/api/chats", headers=h_dev).status_code == 401


def test_devices_cannot_add_or_revoke(env):
    client, h_owner = env()
    with client:
        r = client.post("/api/devices", headers=h_owner, json={"name": "Laptop"})
        data = r.json()
        dev_id = data["device"]["id"]
        dev_token = data["url"].split("#token=")[1]
        h_dev = {"Authorization": f"Bearer {dev_token}"}

        # Device cannot add another device (403)
        assert client.post("/api/devices", headers=h_dev, json={"name": "Another"}).status_code == 403

        # Device cannot revoke a device (403)
        assert client.delete(f"/api/devices/{dev_id}", headers=h_dev).status_code == 403


def test_pair_link_is_owner_only(env):
    client, h_owner = env()
    with client:
        assert client.get("/api/pair", headers=h_owner).status_code == 200

        r = client.post("/api/devices", headers=h_owner, json={"name": "Tablet"})
        dev_token = r.json()["url"].split("#token=")[1]
        h_dev = {"Authorization": f"Bearer {dev_token}"}

        # Device token cannot call /api/pair (403)
        assert client.get("/api/pair", headers=h_dev).status_code == 403


def test_info_reports_who_is_calling(env):
    client, h_owner = env()
    with client:
        info_owner = client.get("/api/info", headers=h_owner).json()
        assert info_owner["me"] == "owner"

        r = client.post("/api/devices", headers=h_owner, json={"name": "Phone"})
        dev_id = r.json()["device"]["id"]
        dev_token = r.json()["url"].split("#token=")[1]
        h_dev = {"Authorization": f"Bearer {dev_token}"}

        info_dev = client.get("/api/info", headers=h_dev).json()
        assert info_dev["me"] == dev_id
# --------------------------------------------------------------------------- C3 usage & alerts
def test_usage_logged_on_finish(env):
    client, h = env()
    with client:
        cid = new_chat(client, h)
        turn(client, h, cid, "hello")
        wait_until_idle(client, h, cid)
        res = client.get("/api/usage?days=7", headers=h)
        assert res.status_code == 200
        days = res.json()["days"]
        claude_days = [d for d in days if d["provider"] == "claude"]
        assert len(claude_days) == 7
        today = claude_days[-1]
        assert today["replies"] >= 1
        assert today["input_tokens"] == 150
        assert today["output_tokens"] == 30
        assert today["errors"] == 0


def test_limits_alert_triggered_once(env, tmp_path):
    client, h = env(limit_alert_percent=60)
    with client:
        cid = new_chat(client, h)
        turn(client, h, cid, "turn 1")
        wait_until_idle(client, h, cid)
        alerts_file = tmp_path / "alerts.json"
        end = time.time() + 10                      # alerts run just after the reply is marked done
        while not alerts_file.exists() and time.time() < end:
            time.sleep(0.1)
        assert alerts_file.exists()
        alert_data = json.loads(alerts_file.read_text(encoding="utf-8"))
        alerted_list = alert_data["alerted"]
        assert len(alerted_list) == 1
        assert "Weekly" in alerted_list[0] or "seven_day" in alerted_list[0]

        # Second turn on same window should not alert again
        turn(client, h, cid, "turn 2")
        wait_until_idle(client, h, cid)
        alert_data2 = json.loads(alerts_file.read_text(encoding="utf-8"))
        assert len(alert_data2["alerted"]) == 1



def test_low_limit_alert_sends_exactly_one_push(env, monkeypatch):
    """C3 + B1 together: a window below the threshold sends one push, and never twice for the same window."""
    sent = []

    def fake_send_all(subs, payload, data_dir, contact):
        sent.append(payload)
        return len(subs.all())

    from agents_dialpad import push
    monkeypatch.setattr(push, "send_all", fake_send_all)
    client, h = env(limit_alert_percent=60)        # the fake claude reports 50 % used of the weekly window
    with client:
        sub = {"endpoint": "https://push.example.com/phone1", "keys": {"p256dh": "key1", "auth": "auth1"}}
        client.post("/api/push/subscribe", headers=h, json={"subscription": sub, "label": "phone"})
        cid = new_chat(client, h)
        for text in ("turn 1", "turn 2"):
            turn(client, h, cid, text)
            wait_until_idle(client, h, cid)
        end = time.time() + 10
        while not [p for p in sent if p.get("tag") == "limits"] and time.time() < end:
            time.sleep(0.1)
        time.sleep(0.5)                            # give a wrongly repeated alert time to show up
        alerts = [p for p in sent if p.get("tag") == "limits"]
        assert len(alerts) == 1
        assert "% left" in alerts[0]["body"] and "pong" not in alerts[0]["body"]   # no conversation content
# --------------------------------------------------------------------------- C4 scheduled prompts
def test_scheduled_prompt_runs_and_records_state(env):
    from datetime import datetime
    now = datetime(2026, 11, 9, 8, 30)  # Monday 08:30
    sched = {
        "name": "Morning digest",
        "at": "08:30",
        "days": ["mon"],
        "project": "workspace",
        "agent": "claude",
        "mode": "readonly",
        "prompt": "Morning summary",
    }
    client, h = env(schedules=[sched])
    with client:
        # Before running tick, list schedules
        res = client.get("/api/schedules", headers=h)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["name"] == "Morning digest"
        assert data[0]["last_run"] is None

        # Tick at exact time creates a chat
        started = client.app.scheduler_tick(now)
        assert len(started) == 1
        cid = started[0]
        wait_until_idle(client, h, cid)

        chat = client.get(f"/api/chats/{cid}", headers=h).json()
        assert chat["title"] == "Morning digest · 2026-11-09"
        assert len(chat["messages"]) >= 2
        assert chat["messages"][0]["text"] == "Morning summary"

        # Calling tick again on the same day creates nothing
        started2 = client.app.scheduler_tick(now)
        assert len(started2) == 0

        # Status updated
        data2 = client.get("/api/schedules", headers=h).json()
        assert data2[0]["last_run"] == "2026-11-09"


def test_run_schedule_now_route(env):
    sched = {
        "name": "Manual run test",
        "at": "02:00",
        "days": ["sun"],
        "project": "workspace",
        "agent": "claude",
        "prompt": "Run now prompt",
    }
    client, h = env(schedules=[sched])
    with client:
        # Missing auth fails
        assert client.post("/api/schedules/Manual%20run%20test/run").status_code == 401
        # Nonexistent fails
        assert client.post("/api/schedules/Nonexistent/run", headers=h).status_code == 404

        res = client.post("/api/schedules/Manual%20run%20test/run", headers=h)
        assert res.status_code == 200
        cid = res.json()["chat_id"]
        wait_until_idle(client, h, cid)
        chat = client.get(f"/api/chats/{cid}", headers=h).json()
        assert "Manual run test" in chat["title"]
        assert chat["messages"][0]["text"] == "Run now prompt"


# --------------------------------------------------------------------------- D1 remove compare
def test_groups_api_is_gone(env):
    client, h = env()
    with client:
        assert client.get("/api/groups/abcd1234", headers=h).status_code == 404


def test_old_clients_sending_group_still_get_a_normal_chat(env):
    client, h = env()
    with client:
        r = client.post("/api/chats", headers=h, json={"provider": "claude", "project": "workspace", "group": "abcd1234"})
        assert r.status_code == 200
        chat = r.json()
        assert "group" not in chat
        loaded = client.get(f"/api/chats/{chat['id']}", headers=h).json()
        assert "group" not in loaded


def test_chats_from_old_compare_groups_still_list(env, tmp_path):
    client, h = env()
    with client:
        cid = "a" * 32
        chat_data = {
            "id": cid,
            "title": "Old compare chat",
            "provider": "claude",
            "project": "workspace",
            "mode": "readonly",
            "model": "",
            "group": "abcd1234",
            "session_id": None,
            "pinned": False,
            "created": time.time(),
            "updated": time.time(),
            "messages": [],
        }
        chats_dir = tmp_path / "chats"
        chats_dir.mkdir(parents=True, exist_ok=True)
        (chats_dir / f"{cid}.json").write_text(json.dumps(chat_data), encoding="utf-8")

        res = client.get("/api/chats", headers=h)
        assert res.status_code == 200
        found = [c for c in res.json()["chats"] if c["id"] == cid]
        assert len(found) == 1
        assert "group" not in found[0]

        get_res = client.get(f"/api/chats/{cid}", headers=h)
        assert get_res.status_code == 200
        assert get_res.json()["title"] == "Old compare chat"


# --------------------------------------------------------------------------- C6 project instructions
def test_per_project_instructions_integration(env, calls, tmp_path):
    (tmp_path / "global.md").write_text("Global rules.", encoding="utf-8")
    (tmp_path / "proj.md").write_text("Project specific rules.", encoding="utf-8")
    (tmp_path / "app").mkdir()
    projects = {
        "workspace": str(tmp_path / "ws"),
        "my-app": {"path": str(tmp_path / "app"), "instructions_file": str(tmp_path / "proj.md")},
    }
    client, h = env(instructions_file=str(tmp_path / "global.md"), projects=projects)
    with client:
        # Chat in my-app project gets global + project instructions
        r = client.post("/api/chats", headers=h, json={"provider": "claude", "project": "my-app", "mode": "readonly"})
        assert r.status_code == 200
        cid_app = r.json()["id"]
        info_app = reply_info(turn(client, h, cid_app, "x"))
        assert info_app["system"] == "Global rules.\n\nProject specific rules."

        # Chat in workspace project gets only global instructions
        cid_ws = new_chat(client, h)
        info_ws = reply_info(turn(client, h, cid_ws, "x"))
        assert info_ws["system"] == "Global rules."






def test_bad_upload_content_length_is_a_400(env):
    client, h = env()
    with client:
        cid = client.post("/api/chats", headers=h, json={"provider": "claude", "project": "workspace"}).json()["id"]
        r = client.put(f"/api/chats/{cid}/uploads?name=a.txt", headers={**h, "Content-Length": "abc"}, content=b"")
        assert r.status_code in (400, 422)


# --------------------------------------------------------------------------- D3 Codex readiness
def test_codex_status_signed_in_and_out(env, monkeypatch):
    from agents_dialpad.providers import codex
    prov = codex.CodexProvider()

    # Signed in
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "signed_in")
    monkeypatch.setattr(codex, "_status_cache", None)
    st = asyncio.run(prov.status())
    assert st["state"] == "ready"
    assert st["note"] == ""

    # Signed out
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "signed_out")
    monkeypatch.setattr(codex, "_status_cache", None)
    st = asyncio.run(prov.status())
    assert st["state"] == "not_signed_in"
    assert "not signed in" in st["note"].lower() or "codex isn't signed in" in st["note"].lower()


def test_codex_status_is_cached(env, calls, monkeypatch):
    from agents_dialpad.providers import codex
    prov = codex.CodexProvider()
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "signed_in")
    monkeypatch.setattr(codex, "_status_cache", None)

    st1 = asyncio.run(prov.status())
    assert st1["state"] == "ready"
    login_calls_1 = [c for c in calls() if "login" in c.get("argv", [])]
    assert len(login_calls_1) == 1

    # Second call uses cache
    st2 = asyncio.run(prov.status())
    assert st2["state"] == "ready"
    login_calls_2 = [c for c in calls() if "login" in c.get("argv", [])]
    assert len(login_calls_2) == 1


def test_info_reports_status_and_hides_disabled_agents(env, monkeypatch):
    from agents_dialpad.providers import codex
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "signed_in")
    monkeypatch.setattr(codex, "_status_cache", None)

    # With codex enabled
    client, auth = env()
    with client:
        r = client.get("/api/info", headers=auth)
        assert r.status_code == 200
        info = r.json()
        prov_names = [p["name"] for p in info["providers"]]
        assert "codex" in prov_names
        codex_p = next(p for p in info["providers"] if p["name"] == "codex")
        assert codex_p["status"]["state"] == "ready"

    # With codex disabled
    client2, auth2 = env(disabled_agents=["codex"])
    with client2:
        r2 = client2.get("/api/info", headers=auth2)
        assert r2.status_code == 200
        info2 = r2.json()
        prov_names2 = [p["name"] for p in info2["providers"]]
        assert "codex" not in prov_names2
        assert "codex" in info2["disabled_agents"]


def test_create_chat_refuses_signed_out_codex(env, monkeypatch):
    from agents_dialpad.providers import codex
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "signed_out")
    monkeypatch.setattr(codex, "_status_cache", None)
    client, auth = env()
    with client:
        r = client.post("/api/chats", headers=auth, json={"project": "workspace", "provider": "codex", "mode": "edit"})
        assert r.status_code == 400
        assert "Codex isn't signed in on the computer" in r.text


def test_codex_default_model_is_passed_when_chat_model_is_default(env, calls, monkeypatch):
    from agents_dialpad.providers import codex
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "signed_in")
    monkeypatch.setattr(codex, "_status_cache", None)
    client, auth = env(codex_default_model="gpt-5.1-custom")
    with client:
        r = client.post("/api/chats", headers=auth, json={"project": "workspace", "provider": "codex", "mode": "edit"})
        assert r.status_code == 200
        chat_id = r.json()["id"]

        r2 = client.post(f"/api/chats/{chat_id}/messages", headers=auth, json={"text": "Hello"})
        assert r2.status_code == 202
        wait_until_idle(client, auth, chat_id)

        # Verify -m gpt-5.1-custom was passed
        c = next(c for c in calls() if c.get("prompt") == "Hello")
        assert "-m" in c["argv"]
        idx = c["argv"].index("-m")
        assert c["argv"][idx + 1] == "gpt-5.1-custom"


def test_codex_error_text_maps_known_errors():
    from agents_dialpad.providers.codex import codex_error_text
    table = [
        (
            '{"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The \'gpt-6.1-sol\' model is not supported when using Codex with a ChatGPT account.","code":"model_not_found"}}',
            "Your Codex account can't use the model 'gpt-6.1-sol'. Pick another model, or set `codex_default_model` in config.json.",
            "change_model",
        ),
        (
            '{"error":{"message":"The requested model is not supported"}}',
            "Your Codex account can't use this model. Pick another model, or set `codex_default_model` in config.json.",
            "change_model",
        ),
        (
            '{"status":401,"error":{"message":"Unauthorized: not logged in"}}',
            "Codex isn't signed in on the computer. Run `codex login` there.",
            None,
        ),
        (
            '{"status":429,"error":{"message":"usage limit exceeded"}}',
            "Codex usage limit reached. Try again later or use another agent.",
            None,
        ),
        (
            'Your OpenAI subscription does not include Codex. Please upgrade your plan.',
            "Your OpenAI account doesn't include Codex. Use a plan that includes it, or sign in with an API key (`codex login --with-api-key`).",
            None,
        ),
        (
            '{"error":{"message":"Internal server error occurred"}}',
            "Internal server error occurred",
            None,
        ),
        (
            'Random unparsed error string without json',
            'Random unparsed error string without json',
            None,
        ),
    ]

    for raw, expected_msg, expected_action in table:
        msg, act = codex_error_text(raw)
        assert msg == expected_msg, f"Expected {expected_msg}, got {msg} for {raw}"
        assert act == expected_action, f"Expected {expected_action}, got {act} for {raw}"


def test_model_not_found_error_has_change_model_action(env, monkeypatch):
    from agents_dialpad.providers import codex
    monkeypatch.setenv("FAKE_CODEX_LOGIN", "signed_in")
    monkeypatch.setattr(codex, "_status_cache", None)
    client, auth = env()
    with client:
        chat_id = new_chat(client, auth, provider="codex", mode="edit")
        events = turn(client, auth, chat_id, "MODEL_NOT_ALLOWED")

        error_evs = [ev for ev in events if ev.get("type") == "error"]
        assert len(error_evs) >= 1
        err = error_evs[0]
        assert err.get("action") == "change_model"
        assert "gpt-6.1-sol" in err.get("message", "")

        done_evs = [ev for ev in events if ev.get("type") == "done"]
        assert len(done_evs) >= 1
        done = done_evs[0]
        assert done.get("is_error") is True
        assert done.get("action") == "change_model"


def test_unknown_disabled_agent_names_are_reported_by_doctor(env, monkeypatch):
    from agents_dialpad import doctor as doctor_mod
    monkeypatch.setenv("AG_CLAUDE", sys.executable)
    monkeypatch.setattr(doctor_mod, "tailscale_checks", lambda port: [])
    client, auth = env(disabled_agents=["codex", "ghost_agent"])

    checks = doctor_mod.run_checks()
    ghost_check = next((c for c in checks if c.label == "Disabled agent" and "ghost_agent" in c.detail), None)
    assert ghost_check is not None
    assert ghost_check.level == "warn"

    codex_check = next((c for c in checks if "Codex" in c.label), None)
    assert codex_check is not None
    assert "turned off in config.json" in codex_check.detail


# --------------------------------------------------------------------------- D4 Lock-screen approvals
def _setup_push_sub(client, h):
    sub = {
        "endpoint": "https://push.example.com/sub/test-1",
        "keys": {"p256dh": "test-p256dh-key", "auth": "test-auth-key"},
    }
    r = client.post("/api/push/subscribe", headers=h, json={"subscription": sub, "label": "phone"})
    assert r.status_code == 200


def test_push_action_allows_with_the_right_token(env, monkeypatch):
    captured_payloads = []
    def mock_send_all(subs, payload, data_dir, contact):
        captured_payloads.append(payload)
        return len(subs.all())
    monkeypatch.setattr(push, "send_all", mock_send_all)

    client, h = env(push_show_commands=True)
    with client:
        _setup_push_sub(client, h)
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})

        end = time.time() + 5
        while time.time() < end and not any("approval" in p for p in captured_payloads):
            time.sleep(0.05)
        payload = next(p for p in captured_payloads if "approval" in p)
        appr = payload["approval"]
        assert appr["can_allow"] is True

        # Send push action with NO auth header
        r = client.post("/push-action", json={
            "chat": cid,
            "req": appr["req"],
            "token": appr["token"],
            "allow": True,
        })
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        wait_until_idle(client, h, cid)
        with client.stream("GET", f"/api/chats/{cid}/stream?start=0", headers=h) as stream_resp:
            events = [json.loads(line) for line in stream_resp.iter_lines() if line and '"ping"' not in line]
        assert any(e.get("type") == "approval_result" and e.get("allow") is True and e.get("by") == "notification" for e in events)


def test_push_action_token_is_single_use(env, monkeypatch):
    captured_payloads = []
    def mock_send_all(subs, payload, data_dir, contact):
        captured_payloads.append(payload)
        return len(subs.all())
    monkeypatch.setattr(push, "send_all", mock_send_all)

    client, h = env(push_show_commands=True)
    with client:
        _setup_push_sub(client, h)
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})

        end = time.time() + 5
        while time.time() < end and not any("approval" in p for p in captured_payloads):
            time.sleep(0.05)
        payload = next(p for p in captured_payloads if "approval" in p)
        appr = payload["approval"]

        r1 = client.post("/push-action", json={
            "chat": cid,
            "req": appr["req"],
            "token": appr["token"],
            "allow": True,
        })
        assert r1.status_code == 200

        # Second POST with the exact same payload returns 409
        r2 = client.post("/push-action", json={
            "chat": cid,
            "req": appr["req"],
            "token": appr["token"],
            "allow": True,
        })
        assert r2.status_code == 409
        assert r2.json() == {"ok": False, "reason": "already_decided"}


def test_push_action_wrong_token_unknown_chat_and_unknown_request_look_the_same(env, monkeypatch):
    captured_payloads = []
    def mock_send_all(subs, payload, data_dir, contact):
        captured_payloads.append(payload)
        return len(subs.all())
    monkeypatch.setattr(push, "send_all", mock_send_all)

    client, h = env()
    with client:
        _setup_push_sub(client, h)
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})

        end = time.time() + 5
        while time.time() < end and not any("approval" in p for p in captured_payloads):
            time.sleep(0.05)
        payload = next(p for p in captured_payloads if "approval" in p)
        appr = payload["approval"]

        r_wrong_tok = client.post("/push-action", json={"chat": cid, "req": appr["req"], "token": "wrong-token-abc", "allow": True})
        r_unk_chat = client.post("/push-action", json={"chat": "0" * 32, "req": appr["req"], "token": appr["token"], "allow": True})
        r_unk_req = client.post("/push-action", json={"chat": cid, "req": "req-unknown", "token": appr["token"], "allow": True})

        assert r_wrong_tok.status_code == 404
        assert r_unk_chat.status_code == 404
        assert r_unk_req.status_code == 404

        assert r_wrong_tok.json() == {"ok": False}
        assert r_unk_chat.json() == {"ok": False}
        assert r_unk_req.json() == {"ok": False}


def test_push_action_token_dies_when_decided_in_app(env, monkeypatch):
    captured_payloads = []
    def mock_send_all(subs, payload, data_dir, contact):
        captured_payloads.append(payload)
        return len(subs.all())
    monkeypatch.setattr(push, "send_all", mock_send_all)

    client, h = env()
    with client:
        _setup_push_sub(client, h)
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})

        end = time.time() + 5
        while time.time() < end and not any("approval" in p for p in captured_payloads):
            time.sleep(0.05)
        payload = next(p for p in captured_payloads if "approval" in p)
        appr = payload["approval"]

        # Decide in app via regular API
        r_app = client.post(f"/api/chats/{cid}/approvals/{appr['req']}", headers=h, json={"allow": True})
        assert r_app.status_code == 200

        # POST to /push-action must be rejected (409 or 404, never 200)
        r_push = client.post("/push-action", json={
            "chat": cid,
            "req": appr["req"],
            "token": appr["token"],
            "allow": True,
        })
        assert r_push.status_code in (404, 409)
        assert r_push.status_code != 200


def test_push_action_after_timeout_is_rejected(env, monkeypatch):
    captured_payloads = []
    def mock_send_all(subs, payload, data_dir, contact):
        captured_payloads.append(payload)
        return len(subs.all())
    monkeypatch.setattr(push, "send_all", mock_send_all)
    monkeypatch.setenv("AG_APPROVAL_TIMEOUT", "1")

    client, h = env()
    with client:
        _setup_push_sub(client, h)
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})

        end = time.time() + 5
        while time.time() < end and not any("approval" in p for p in captured_payloads):
            time.sleep(0.05)
        payload = next(p for p in captured_payloads if "approval" in p)
        appr = payload["approval"]

        # Wait until timeout expires and run becomes idle
        wait_until_idle(client, h, cid, timeout=10)

        # POST to /push-action must fail
        r = client.post("/push-action", json={
            "chat": cid,
            "req": appr["req"],
            "token": appr["token"],
            "allow": True,
        })
        assert r.status_code in (404, 409)
        assert r.status_code != 200


def test_command_is_only_in_the_payload_when_opted_in(env, monkeypatch):
    captured_payloads = []
    def mock_send_all(subs, payload, data_dir, contact):
        captured_payloads.append(payload)
        return len(subs.all())
    monkeypatch.setattr(push, "send_all", mock_send_all)

    # Opted out by default
    client1, h1 = env(push_show_commands=False)
    with client1:
        _setup_push_sub(client1, h1)
        cid1 = new_chat(client1, h1, mode="ask")
        client1.post(f"/api/chats/{cid1}/messages", headers=h1, json={"text": "NEEDS_APPROVAL"})

        end = time.time() + 5
        while time.time() < end and not captured_payloads:
            time.sleep(0.05)
        p1 = captured_payloads[-1]
        assert p1["body"] == "Open to see what it wants to do"
        assert p1["approval"]["can_allow"] is False

    captured_payloads.clear()

    # Opted in
    client2, h2 = env(push_show_commands=True)
    with client2:
        _setup_push_sub(client2, h2)
        cid2 = new_chat(client2, h2, mode="ask")
        client2.post(f"/api/chats/{cid2}/messages", headers=h2, json={"text": "NEEDS_APPROVAL"})

        end = time.time() + 5
        while time.time() < end and not captured_payloads:
            time.sleep(0.05)
        p2 = captured_payloads[-1]
        assert "echo hi" in p2["body"]
        assert p2["approval"]["can_allow"] is True


def test_push_action_rejects_bodies_over_1kb(env):
    client, h = env()
    with client:
        big_body = json.dumps({
            "chat": "0" * 32,
            "req": "req-1",
            "token": "x" * 1100,
            "allow": True,
        })
        r = client.post("/push-action", content=big_body, headers={"Content-Type": "application/json"})
        assert r.status_code in (413, 400)


def test_token_is_never_logged(env, monkeypatch, caplog, capsys):
    import logging
    caplog.set_level(logging.DEBUG)

    captured_payloads = []
    def mock_send_all(subs, payload, data_dir, contact):
        captured_payloads.append(payload)
        return len(subs.all())
    monkeypatch.setattr(push, "send_all", mock_send_all)

    client, h = env(push_show_commands=True)
    with client:
        _setup_push_sub(client, h)
        cid = new_chat(client, h, mode="ask")
        client.post(f"/api/chats/{cid}/messages", headers=h, json={"text": "NEEDS_APPROVAL"})

        end = time.time() + 5
        while time.time() < end and not any("approval" in p for p in captured_payloads):
            time.sleep(0.05)
        payload = next(p for p in captured_payloads if "approval" in p)
        plain_token = payload["approval"]["token"]

        r = client.post("/push-action", json={
            "chat": cid,
            "req": payload["approval"]["req"],
            "token": plain_token,
            "allow": True,
        })
        assert r.status_code == 200

    out, err = capsys.readouterr()
    assert plain_token not in out
    assert plain_token not in err
    for record in caplog.records:
        assert plain_token not in record.getMessage()


# ------------------------------------------------------------------ G1: Files API

def test_files_routes_need_the_token(env):
    client, h = env()
    # No auth header -> 401
    r_list = client.get("/api/projects/workspace/files")
    assert r_list.status_code == 401

    r_meta = client.get("/api/projects/workspace/files/meta?path=a.txt")
    assert r_meta.status_code == 401

    r_content = client.get("/api/projects/workspace/files/content?path=a.txt")
    assert r_content.status_code == 401


def test_files_list_and_read_text_file(env):
    client, h = env()
    ws = config.DATA / "ws"
    (ws / "hello.txt").write_text("Hello, dialpad files!", encoding="utf-8")
    (ws / "sub").mkdir(exist_ok=True)
    (ws / "sub" / "nested.py").write_text("print('nested')", encoding="utf-8")

    # List root
    r = client.get("/api/projects/workspace/files", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == ""
    assert data["truncated"] is False
    names = [e["name"] for e in data["entries"]]
    assert "sub" in names
    assert "hello.txt" in names

    # Meta
    r_meta = client.get("/api/projects/workspace/files/meta?path=hello.txt", headers=h)
    assert r_meta.status_code == 200
    meta = r_meta.json()
    assert meta["name"] == "hello.txt"
    assert meta["kind"] == "text"
    assert meta["binary"] is False
    assert meta["previewable"] is True
    assert meta["truncated_at"] is None

    # Content
    r_content = client.get("/api/projects/workspace/files/content?path=hello.txt", headers=h)
    assert r_content.status_code == 200
    assert r_content.text == "Hello, dialpad files!"


def test_files_content_has_security_headers(env):
    client, h = env()
    ws = config.DATA / "ws"
    (ws / "sample.txt").write_text("security check", encoding="utf-8")

    r = client.get("/api/projects/workspace/files/content?path=sample.txt", headers=h)
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "no-store" in r.headers.get("Cache-Control", "")
    assert "sandbox" in r.headers.get("Content-Security-Policy", "")


def test_files_content_supports_range(env):
    client, h = env()
    ws = config.DATA / "ws"
    content = b"0123456789" * 100
    (ws / "range.bin").write_bytes(content)

    r = client.get(
        "/api/projects/workspace/files/content?path=range.bin",
        headers={**h, "Range": "bytes=10-29"},
    )
    assert r.status_code == 206
    assert r.headers.get("Content-Range") == f"bytes 10-29/{len(content)}"
    assert r.content == content[10:30]


def test_large_text_file_is_truncated_at_one_megabyte(env):
    client, h = env()
    ws = config.DATA / "ws"
    big_size = 1_048_576 + 500
    (ws / "large.txt").write_bytes(b"a" * big_size)

    # download=0 -> truncated at 1 MB
    r = client.get("/api/projects/workspace/files/content?path=large.txt&download=0", headers=h)
    assert r.status_code == 200
    assert r.headers.get("X-Truncated") == "1"
    assert len(r.content) == 1_048_576

    # download=1 -> not truncated
    r_dl = client.get("/api/projects/workspace/files/content?path=large.txt&download=1", headers=h)
    assert r_dl.status_code == 200
    assert "X-Truncated" not in r_dl.headers
    assert len(r_dl.content) == big_size


def test_data_folder_token_is_not_readable_through_a_project(env):
    # Set up client first
    client, h = env()
    # Configure project pointing to folder containing config.DATA
    parent = config.DATA.parent
    (config.DATA / "token.txt").write_text("secret_tok", encoding="utf-8")
    client, h = env(projects={"parent": str(parent)})

    rel_token = f"{config.DATA.name}/token.txt"
    r = client.get(f"/api/projects/parent/files/content?path={rel_token}", headers=h)
    assert r.status_code == 404

    r_list = client.get("/api/projects/parent/files", headers=h)
    assert r_list.status_code == 200
    names = [e["name"] for e in r_list.json()["entries"]]
    assert config.DATA.name not in names


def test_file_viewer_off_returns_404(env):
    client, h = env(file_viewer=False)
    ws = config.DATA / "ws"
    (ws / "test.txt").write_text("test", encoding="utf-8")

    # /api/info reports file_viewer: False
    info = client.get("/api/info", headers=h).json()
    assert info["file_viewer"] is False

    # Routes return 404
    assert client.get("/api/projects/workspace/files", headers=h).status_code == 404
    assert client.get("/api/projects/workspace/files/meta?path=test.txt", headers=h).status_code == 404
    assert client.get("/api/projects/workspace/files/content?path=test.txt", headers=h).status_code == 404


def test_locked_device_gets_423_on_files(env):
    from agents_dialpad import applock

    client, h = env()
    ws = config.DATA / "ws"
    (ws / "secret.txt").write_text("passkey protected", encoding="utf-8")

    # Set a passkey for owner in LockStore
    store = applock.LockStore(config.DATA / "lock.json")
    store.add("owner", {
        "id": "test_cred_id",
        "public_key": "dummy_pk",
        "sign_count": 0,
        "name": "Owner Key",
        "created_at": "2026-01-01T00:00:00Z",
    })

    # Without X-Unlock -> 423 Locked
    r_list = client.get("/api/projects/workspace/files", headers=h)
    assert r_list.status_code == 423

    r_meta = client.get("/api/projects/workspace/files/meta?path=secret.txt", headers=h)
    assert r_meta.status_code == 423

    r_content = client.get("/api/projects/workspace/files/content?path=secret.txt", headers=h)
    assert r_content.status_code == 423


