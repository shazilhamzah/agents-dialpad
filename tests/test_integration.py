"""End-to-end tests: the real FastAPI app, real subprocesses, with fake `claude` / `agy` CLIs (no subscriptions needed)."""
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents_dialpad import config, pairing
from agents_dialpad.app import create_app
from agents_dialpad.keepawake import KeepAwake
from agents_dialpad.providers import antigravity

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
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setattr(antigravity, "_models_cache", None)
    monkeypatch.setattr(antigravity, "_limits_cache", None)
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
        assert agents["claude"]["available"] and agents["antigravity"]["available"] and not agents["codex"]["available"]
        assert [m["id"] for m in agents["antigravity"]["models"]][:2] == ["", "gemini-test-low"]
        assert info["projects"] == ["workspace"]
        assert [m["id"] for m in info["modes"]] == ["readonly", "edit"]       # no full access unless enabled


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
        assert client.post("/api/chats", headers=h, json={"provider": "codex", "project": "workspace"}).status_code == 400
        assert client.get("/api/chats/..%5C..%5Cconfig", headers=h).status_code == 404


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


