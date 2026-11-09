"""Unit tests for attachment uploads."""
import pytest
from fastapi import HTTPException
from agents_dialpad import config, uploads


def test_safe_name_handles_various_inputs():
    assert uploads.safe_name("../../hello.png") == "hello.png"
    assert uploads.safe_name("unicode 🚀 file.jpg") == "unicode-file.jpg"
    assert uploads.safe_name("a" * 100 + ".txt") == ("a" * 76) + ".txt"
    assert uploads.safe_name("") == "file"
    assert uploads.safe_name("noext") == "noext"
    assert uploads.safe_name("bad/\\../name.py") == "name.py"


def test_type_check_allows_and_rejects_extensions(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)

    # Allowed extensions
    res = uploads.save("chat1", "screenshot.png", b"fake png data")
    assert res["name"].endswith("-screenshot.png")
    assert res["size"] == len(b"fake png data")

    res_py = uploads.save("chat1", "script.py", b"print(1)")
    assert res_py["name"].endswith("-script.py")

    # Rejected extensions
    with pytest.raises(HTTPException) as exc:
        uploads.save("chat1", "evil.exe", b"malware")
    assert exc.value.status_code == 415

    with pytest.raises(HTTPException) as exc:
        uploads.save("chat1", "script.sh", b"echo hi")
    assert exc.value.status_code == 415


def test_file_and_chat_size_totals(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)

    # Exceeding single file limit (15 MB)
    with pytest.raises(HTTPException) as exc:
        uploads.save("chat1", "big.txt", b"x" * (uploads.MAX_FILE + 1))
    assert exc.value.status_code == 413
    assert "larger than 15 MB" in exc.value.detail

    # Exceeding chat total limit (200 MB)
    monkeypatch.setattr(uploads, "MAX_CHAT_TOTAL", 100)
    uploads.save("chat1", "small1.txt", b"x" * 60)
    with pytest.raises(HTTPException) as exc:
        uploads.save("chat1", "small2.txt", b"x" * 50)
    assert exc.value.status_code == 413
    assert "limit exceeded" in exc.value.detail


def test_resolve_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)

    res1 = uploads.save("chat1", "file1.txt", b"content 1")
    res2 = uploads.save("chat2", "file2.txt", b"content 2")

    # Resolves files belonging to chat1
    paths = uploads.resolve("chat1", [res1["name"]])
    assert len(paths) == 1
    assert paths[0].is_file()
    assert paths[0].read_bytes() == b"content 1"

    # Reject file from another chat
    with pytest.raises(ValueError):
        uploads.resolve("chat1", [res2["name"]])

    # Reject non-existent file
    with pytest.raises(ValueError):
        uploads.resolve("chat1", ["nonexistent-file.txt"])

    # Reject path traversal attempts
    with pytest.raises(ValueError):
        uploads.resolve("chat1", ["../chat2/" + res2["name"]])
    with pytest.raises(ValueError):
        uploads.resolve("chat1", ["sub/file.txt"])
    with pytest.raises(ValueError):
        uploads.resolve("chat1", [""])


def test_remove_all(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)

    uploads.save("chat1", "file.txt", b"test")
    udir = uploads.upload_dir("chat1")
    assert udir.exists()
    assert len(list(udir.glob("*"))) == 1

    uploads.remove_all("chat1")
    assert not udir.exists()
