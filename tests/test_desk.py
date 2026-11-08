"""Unit tests for Claude Code desktop sessions."""
import json
import os
import time
from pathlib import Path

import pytest
from agents_dialpad import desk


def make_session(
    claude_dir: Path,
    session_id: str,
    cwd: str,
    records: list[dict],
    mtime: float | None = None,
) -> Path:
    proj_folder = claude_dir / "projects" / "test-project"
    proj_folder.mkdir(parents=True, exist_ok=True)
    p = proj_folder / f"{session_id}.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_lists_sessions_for_the_matching_folder_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    dir_a = str(tmp_path / "app-a")
    dir_b = str(tmp_path / "app-b")

    id_a = "11111111-1111-1111-1111-111111111111"
    id_b = "22222222-2222-2222-2222-222222222222"

    make_session(
        tmp_path,
        id_a,
        dir_a,
        [
            {"type": "user", "cwd": dir_a, "message": {"content": "Hello in A"}},
        ],
    )
    make_session(
        tmp_path,
        id_b,
        dir_b,
        [
            {"type": "user", "cwd": dir_b, "message": {"content": "Hello in B"}},
        ],
    )

    res_a = desk.list_sessions(dir_a, exclude_ids=set())
    assert len(res_a) == 1
    assert res_a[0]["id"] == id_a
    assert res_a[0]["preview"] == "Hello in A"

    res_b = desk.list_sessions(dir_b, exclude_ids=set())
    assert len(res_b) == 1
    assert res_b[0]["id"] == id_b
    assert res_b[0]["preview"] == "Hello in B"


def test_preview_is_the_first_real_user_message(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    target_dir = str(tmp_path / "target")
    sid = "33333333-3333-3333-3333-333333333333"

    records = [
        {"type": "queue-operation", "operation": "enqueue"},
        {"type": "user", "cwd": target_dir, "isSidechain": True, "message": "sidechain message"},
        {"type": "user", "cwd": target_dir, "message": [{"type": "tool_result", "text": "result"}]},
        {"type": "user", "cwd": target_dir, "message": "<command-name>do something</command-name>"},
        {"type": "user", "cwd": target_dir, "message": [{"type": "text", "text": "  Real question here  "}]},
        {"type": "user", "cwd": target_dir, "message": "Second message"},
    ]
    make_session(tmp_path, sid, target_dir, records)

    res = desk.list_sessions(target_dir, exclude_ids=set())
    assert len(res) == 1
    assert res[0]["preview"] == "Real question here"


def test_newest_first_and_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    target_dir = str(tmp_path / "target")

    now = time.time()
    id_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    id_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    id_3 = "cccccccc-cccc-cccc-cccc-cccccccccccc"

    make_session(tmp_path, id_1, target_dir, [{"type": "user", "cwd": target_dir, "message": "msg 1"}], mtime=now - 200)
    make_session(tmp_path, id_2, target_dir, [{"type": "user", "cwd": target_dir, "message": "msg 2"}], mtime=now - 50)
    make_session(tmp_path, id_3, target_dir, [{"type": "user", "cwd": target_dir, "message": "msg 3"}], mtime=now - 100)

    # Sorted newest first: id_2 (newest), then id_3, then id_1
    res = desk.list_sessions(target_dir, exclude_ids=set())
    assert [r["id"] for r in res] == [id_2, id_3, id_1]

    # Limit
    res_limited = desk.list_sessions(target_dir, exclude_ids=set(), limit=2)
    assert [r["id"] for r in res_limited] == [id_2, id_3]


def test_excluded_ids_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    target_dir = str(tmp_path / "target")

    id_1 = "aaaaaaaa-1111-aaaa-aaaa-aaaaaaaaaaaa"
    id_2 = "bbbbbbbb-2222-bbbb-bbbb-bbbbbbbbbbbb"

    make_session(tmp_path, id_1, target_dir, [{"type": "user", "cwd": target_dir, "message": "first"}])
    make_session(tmp_path, id_2, target_dir, [{"type": "user", "cwd": target_dir, "message": "second"}])

    res = desk.list_sessions(target_dir, exclude_ids={id_1})
    assert len(res) == 1
    assert res[0]["id"] == id_2


def test_garbage_lines_and_non_uuid_files_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    target_dir = str(tmp_path / "target")

    # Non-uuid file
    proj_folder = tmp_path / "projects" / "test-project"
    proj_folder.mkdir(parents=True, exist_ok=True)
    (proj_folder / "not-a-uuid.jsonl").write_text(
        json.dumps({"type": "user", "cwd": target_dir, "message": "hello"}) + "\n",
        encoding="utf-8",
    )

    # Valid UUID file with corrupted/garbage lines before real user line
    sid = "44444444-4444-4444-4444-444444444444"
    p = proj_folder / f"{sid}.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write("NOT JSON AT ALL\n")
        f.write("\n")
        f.write("{corrupt json\n")
        f.write("42\n")
        f.write(json.dumps({"type": "user", "cwd": target_dir, "message": "Valid after garbage"}) + "\n")

    res = desk.list_sessions(target_dir, exclude_ids=set())
    assert len(res) == 1
    assert res[0]["id"] == sid
    assert res[0]["preview"] == "Valid after garbage"


def test_session_belongs_to_checks_the_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    dir_a = str(tmp_path / "proj-a")
    dir_b = str(tmp_path / "proj-b")

    sid = "55555555-5555-5555-5555-555555555555"
    make_session(tmp_path, sid, dir_a, [{"type": "user", "cwd": dir_a, "message": "hello"}])

    assert desk.session_belongs_to(dir_a, sid) is True
    assert desk.session_belongs_to(dir_b, sid) is False
    assert desk.session_belongs_to(dir_a, "00000000-0000-0000-0000-000000000000") is False
    assert desk.session_belongs_to(dir_a, "invalid-uuid") is False
