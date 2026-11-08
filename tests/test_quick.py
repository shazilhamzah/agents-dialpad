"""Unit tests for quick commands."""
import asyncio
import sys
import pytest

from agents_dialpad import quick


def test_normalize_keeps_valid_entries_and_reports_bad_ones():
    raw = {
        "*": [
            {"label": "Valid", "run": ["git", "status"], "timeout": 60},
            {"label": "No Run", "run": "git status"},  # string run
            {"label": "Empty Run", "run": []},  # empty list
            {"label": "x" * 41, "run": ["git", "status"]},  # label too long
            {"label": "Zero Timeout", "run": ["git", "status"], "timeout": 0},  # timeout 0
            {"label": "Too Large Timeout", "run": ["git", "status"], "timeout": 3600},  # timeout 3600
        ],
        "my-proj": [
            {"label": "Test", "run": ["pytest"]},
        ],
    }
    clean, problems = quick.normalize(raw)
    assert len(clean["*"]) == 1
    assert clean["*"][0]["label"] == "Valid"
    assert clean["*"][0]["timeout"] == 60
    assert len(clean["my-proj"]) == 1
    assert clean["my-proj"][0]["label"] == "Test"
    assert clean["my-proj"][0]["timeout"] == 120  # default
    assert len(problems) == 5


def test_global_commands_come_first():
    mapping = {
        "*": [{"label": "Global 1", "run": ["echo", "1"], "timeout": 10}],
        "proj": [{"label": "Proj 1", "run": ["echo", "2"], "timeout": 20}],
    }
    cmds = quick.commands_for(mapping, "proj")
    assert [c["label"] for c in cmds] == ["Global 1", "Proj 1"]
    assert [c["index"] for c in cmds] == [0, 1]


def test_run_returns_output_and_exit_code(tmp_path):
    res = asyncio.run(quick.run([sys.executable, "-c", "print('hi')"], cwd=str(tmp_path), timeout=10))
    assert res["exit_code"] == 0
    assert "hi" in res["output"]
    assert res["timed_out"] is False
    assert res["truncated"] is False


def test_nonzero_exit_code_is_reported(tmp_path):
    res = asyncio.run(quick.run([sys.executable, "-c", "import sys; sys.exit(3)"], cwd=str(tmp_path), timeout=10))
    assert res["exit_code"] == 3
    assert res["timed_out"] is False


def test_timeout_kills_the_process(tmp_path):
    res = asyncio.run(quick.run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path), timeout=1))
    assert res["timed_out"] is True
    assert res["exit_code"] is None


def test_long_output_is_truncated_from_the_start(tmp_path):
    code = "print('a' * 30000 + 'b' * 30000)"
    res = asyncio.run(quick.run([sys.executable, "-c", code], cwd=str(tmp_path), timeout=10))
    assert res["truncated"] is True
    assert "output truncated" in res["output"]
    assert res["output"].rstrip().endswith("b" * 1000)


def test_missing_program_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        asyncio.run(quick.run(["definitely_not_a_program_xyz_123"], cwd=str(tmp_path), timeout=5))
