import json
from agents_dialpad.approvals import approval_event, MAX_CHARS


def test_approval_event_picks_command():
    ev = approval_event("r1", "Bash", {"command": "echo hello"}, "desc")
    assert ev["id"] == "r1"
    assert ev["tool"] == "Bash"
    assert ev["command"] == "echo hello"
    assert ev["description"] == "desc"
    assert ev["input"] == {"command": "echo hello"}
    assert ev["truncated"] is False


def test_approval_event_picks_commandline():
    ev = approval_event("r2", "run_command", {"CommandLine": "dir /s", "WaitMsBeforeAsync": 5000})
    assert ev["command"] == "dir /s"
    assert ev["tool"] == "run_command"
    assert ev["truncated"] is False


def test_approval_event_picks_file_path():
    ev = approval_event("r3", "Edit", {"file_path": "src/app.py", "old_string": "a", "new_string": "b"})
    assert ev["command"] == "src/app.py"
    assert ev["truncated"] is False


def test_approval_event_picks_json_for_unknown():
    raw = {"foo": "bar", "num": 42}
    ev = approval_event("r4", "CustomTool", raw)
    assert ev["command"] == json.dumps(raw, ensure_ascii=False)
    assert ev["truncated"] is False


def test_approval_event_truncation_on_long_command():
    long_cmd = "x" * 25_000
    ev = approval_event("r5", "Bash", {"command": long_cmd})
    assert len(ev["command"]) == MAX_CHARS
    assert ev["command"] == "x" * MAX_CHARS
    assert len(ev["input"]["command"]) == MAX_CHARS
    assert ev["truncated"] is True


def test_approval_event_truncation_on_nested_input():
    long_str = "y" * 25_000
    ev = approval_event("r6", "Bash", {"command": "short", "data": {"nested": long_str}})
    assert ev["command"] == "short"
    assert len(ev["input"]["data"]["nested"]) == MAX_CHARS
    assert ev["truncated"] is True
