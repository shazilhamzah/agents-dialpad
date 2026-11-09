"""Unit tests for gitview."""
import asyncio
import subprocess
from pathlib import Path

import pytest
from agents_dialpad import gitview


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def init_repo(repo: Path) -> None:
    run_git(repo, "init")
    run_git(repo, "-c", "user.name=Test", "-c", "user.email=t@e.com", "commit", "--allow-empty", "-m", "init")


def test_not_a_repo_is_reported(tmp_path):
    res = asyncio.run(gitview.status(tmp_path))
    assert res == {"is_repo": False, "files": []}


def test_status_lists_modified_added_deleted_and_untracked(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "mod.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "del.txt").write_text("goodbye\n", encoding="utf-8")
    run_git(tmp_path, "add", "mod.txt", "del.txt")
    run_git(tmp_path, "-c", "user.name=Test", "-c", "user.email=t@e.com", "commit", "-m", "add files")

    # Modify mod.txt, delete del.txt, add untracked.txt, stage add new_staged.txt
    (tmp_path / "mod.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "del.txt").unlink()
    (tmp_path / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (tmp_path / "staged.txt").write_text("staged\n", encoding="utf-8")
    run_git(tmp_path, "add", "staged.txt")

    res = asyncio.run(gitview.status(tmp_path))
    assert res["is_repo"] is True
    assert res["branch"] is not None

    files_by_path = {f["path"]: f for f in res["files"]}
    assert "mod.txt" in files_by_path
    assert files_by_path["mod.txt"]["code"] == "M"
    assert files_by_path["mod.txt"]["label"] == "modified"

    assert "del.txt" in files_by_path
    assert files_by_path["del.txt"]["code"] == "D"
    assert files_by_path["del.txt"]["label"] == "deleted"

    assert "untracked.txt" in files_by_path
    assert files_by_path["untracked.txt"]["code"] == "??"
    assert files_by_path["untracked.txt"]["label"] == "untracked"

    assert "staged.txt" in files_by_path
    assert files_by_path["staged.txt"]["code"] == "A"
    assert files_by_path["staged.txt"]["label"] == "added"


def test_renames_report_both_paths(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "old.txt").write_text("rename me\n", encoding="utf-8")
    run_git(tmp_path, "add", "old.txt")
    run_git(tmp_path, "-c", "user.name=Test", "-c", "user.email=t@e.com", "commit", "-m", "add old")

    run_git(tmp_path, "mv", "old.txt", "new.txt")

    res = asyncio.run(gitview.status(tmp_path))
    assert res["is_repo"] is True
    files = res["files"]
    rename_entry = next((f for f in files if f["path"] == "new.txt"), None)
    assert rename_entry is not None
    assert rename_entry["code"] == "R"
    assert rename_entry["label"] == "renamed"
    assert rename_entry["orig_path"] == "old.txt"


def test_diff_of_a_modified_file_has_added_and_removed_lines(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "doc.txt").write_text("line 1\nline 2\n", encoding="utf-8")
    run_git(tmp_path, "add", "doc.txt")
    run_git(tmp_path, "-c", "user.name=Test", "-c", "user.email=t@e.com", "commit", "-m", "add doc")

    (tmp_path / "doc.txt").write_text("line 1\nline 2 modified\nline 3\n", encoding="utf-8")

    res = asyncio.run(gitview.diff(tmp_path, "doc.txt"))
    assert res["path"] == "doc.txt"
    assert res["kind"] == "text"
    assert res["truncated"] is False
    assert "-line 2" in res["diff"]
    assert "+line 2 modified" in res["diff"]
    assert "+line 3" in res["diff"]


def test_untracked_text_file_becomes_an_all_added_diff(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "notes.txt").write_text("first\nsecond\n", encoding="utf-8")

    res = asyncio.run(gitview.diff(tmp_path, "notes.txt"))
    assert res["path"] == "notes.txt"
    assert res["kind"] == "untracked"
    assert res["truncated"] is False
    lines = res["diff"].splitlines()
    assert lines == ["+first", "+second"]


def test_binary_untracked_file_is_not_shown(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02\x03\xff")

    res = asyncio.run(gitview.diff(tmp_path, "binary.bin"))
    assert res["path"] == "binary.bin"
    assert res["kind"] == "binary"
    assert res["diff"] == ""
    assert res["truncated"] is False


def test_diff_is_truncated_when_huge(tmp_path, monkeypatch):
    init_repo(tmp_path)
    monkeypatch.setattr(gitview, "MAX_DIFF", 100)
    (tmp_path / "big.txt").write_text("a" * 500 + "\n", encoding="utf-8")

    res = asyncio.run(gitview.diff(tmp_path, "big.txt"))
    assert res["truncated"] is True
    assert len(res["diff"]) == 100


def test_revert_restores_a_tracked_file(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("original\n", encoding="utf-8")
    run_git(tmp_path, "add", "file.txt")
    run_git(tmp_path, "-c", "user.name=Test", "-c", "user.email=t@e.com", "commit", "-m", "add file")

    (tmp_path / "file.txt").write_text("changed\n", encoding="utf-8")
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "changed\n"

    asyncio.run(gitview.revert(tmp_path, "file.txt"))
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "original\n"


def test_revert_refuses_new_files(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "new_file.txt").write_text("brand new\n", encoding="utf-8")

    with pytest.raises(LookupError):
        asyncio.run(gitview.revert(tmp_path, "new_file.txt"))


def test_paths_outside_the_project_are_rejected(tmp_path):
    bad_paths = [
        "../x",
        "/etc/passwd",
        "C:\\x",
        "a/../../x",
        "",
        "a\0b",
    ]
    for p in bad_paths:
        with pytest.raises(ValueError):
            gitview.safe_path(tmp_path, p)


def test_revert_refuses_folders_and_globs(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("b\n", encoding="utf-8")
    run_git(tmp_path, "add", "src")
    run_git(tmp_path, "-c", "user.name=Test", "-c", "user.email=t@e.com", "commit", "-m", "add src")
    (tmp_path / "src" / "a.txt").write_text("a changed\n", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("b changed\n", encoding="utf-8")

    with pytest.raises(ValueError):
        asyncio.run(gitview.revert(tmp_path, "src"))
    with pytest.raises((LookupError, ValueError)):
        asyncio.run(gitview.revert(tmp_path, "src/*.txt"))
    assert (tmp_path / "src" / "a.txt").read_text(encoding="utf-8") == "a changed\n"
    assert (tmp_path / "src" / "b.txt").read_text(encoding="utf-8") == "b changed\n"
