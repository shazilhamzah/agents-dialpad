"""Unit tests for agents_dialpad.files module."""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from agents_dialpad import files


def test_resolve_rejects_traversal(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Traversal and invalid patterns
    bad_paths = [
        "../x",
        "a/../../x",
        "a\\..\\..\\x",
        "/etc/passwd",
        "\\Windows\\System32",
        "C:\\autoexec.bat",
        "\\\\server\\share\\file.txt",
        "file\0name.txt",
        "",
        ".",
    ]
    for bad in bad_paths:
        with pytest.raises(ValueError):
            files.resolve(root, bad, data_dir=data_dir, allow_root=False)


def test_resolve_rejects_alternate_data_streams_and_reserved_names(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    bad_names = [
        "a.txt:s",
        "a.txt::$DATA",
        "CON",
        "con.txt",
        "PRN",
        "prn.dat",
        "AUX",
        "NUL",
        "nul.txt",
        "COM1",
        "com2.txt",
        "LPT1",
        "lpt9.log",
        "x.",
        "x ",
        "folder/nul.txt",
    ]
    for bad in bad_names:
        with pytest.raises(ValueError):
            files.resolve(root, bad, data_dir=data_dir)


def test_resolve_rejects_symlink_that_escapes_root(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    link = root / "link_to_secret.txt"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"Symlinks not supported in this environment: {e}")

    with pytest.raises(FileNotFoundError) as exc_info:
        files.resolve(root, "link_to_secret.txt", data_dir=data_dir)
    assert "File not found" in str(exc_info.value)


def test_resolve_denies_data_dir_and_dot_git_and_secret_names(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    data_dir = root / "data"  # data folder inside project
    data_dir.mkdir()
    (data_dir / "token.txt").write_text("secret_token", encoding="utf-8")

    git_dir = root / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("git config", encoding="utf-8")

    (root / ".env").write_text("API_KEY=123", encoding="utf-8")
    (root / ".env.local").write_text("API_KEY=123", encoding="utf-8")
    (root / "key.pem").write_text("pem", encoding="utf-8")
    (root / "id_rsa").write_text("rsa", encoding="utf-8")
    (root / "id_ed25519").write_text("ed25519", encoding="utf-8")
    (root / ".env.example").write_text("EXAMPLE=1", encoding="utf-8")
    (root / "id_rsa.pub").write_text("public_key", encoding="utf-8")

    # Inside data_dir -> 404
    with pytest.raises(FileNotFoundError):
        files.resolve(root, "data/token.txt", data_dir=data_dir)

    # Inside .git -> 404
    with pytest.raises(FileNotFoundError):
        files.resolve(root, ".git/config", data_dir=data_dir)

    # Secret files -> 404
    for denied in [".env", ".env.local", "key.pem", "id_rsa", "id_ed25519"]:
        with pytest.raises(FileNotFoundError):
            files.resolve(root, denied, data_dir=data_dir)

    # Allowed despite deny pattern
    allowed_example = files.resolve(root, ".env.example", data_dir=data_dir)
    assert allowed_example.name == ".env.example"

    allowed_pub = files.resolve(root, "id_rsa.pub", data_dir=data_dir)
    assert allowed_pub.name == "id_rsa.pub"


def test_denied_and_missing_look_identical(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    (root / ".env").write_text("SECRET=1", encoding="utf-8")

    with pytest.raises(FileNotFoundError) as exc_denied:
        files.resolve(root, ".env", data_dir=data_dir)

    with pytest.raises(FileNotFoundError) as exc_missing:
        files.resolve(root, "nonexistent.txt", data_dir=data_dir)

    assert str(exc_denied.value) == str(exc_missing.value)
    assert type(exc_denied.value) is type(exc_missing.value)


def test_list_dir_sorts_hides_dot_git_and_denied_and_truncates(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Create .git and denied file
    git_dir = root / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref", encoding="utf-8")
    (root / ".env").write_text("SECRET=1", encoding="utf-8")

    # Create directories (mixed case)
    (root / "src").mkdir()
    (root / "assets").mkdir()
    (root / "docs").mkdir()

    # Create 1,005 files (named f_0000 to f_1004)
    for i in range(1005):
        (root / f"file_{i:04d}.txt").write_text("x", encoding="utf-8")

    res = files.list_dir(root, "", data_dir=data_dir)
    assert res["path"] == ""
    assert res["truncated"] is True
    assert len(res["entries"]) == files.MAX_LIST

    # .git and .env must not be in listing
    names = [e["name"] for e in res["entries"]]
    assert ".git" not in names
    assert ".env" not in names

    # Directories must come first, case-insensitively sorted
    dir_names = [e["name"] for e in res["entries"] if e["kind"] == "dir"]
    assert dir_names == ["assets", "docs", "src"]

    # Files follow directories, case-insensitively sorted
    file_entries = [e for e in res["entries"] if e["kind"] == "file"]
    file_names = [e["name"] for e in file_entries]
    assert file_names == sorted(file_names, key=lambda x: x.lower())


def test_kind_and_media_type_never_return_html_or_svg_inline(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()

    html_file = root / "index.html"
    html_file.write_text("<h1>hello</h1>", encoding="utf-8")

    svg_file = root / "graphic.svg"
    svg_file.write_text("<svg></svg>", encoding="utf-8")

    xml_file = root / "data.xml"
    xml_file.write_text("<xml></xml>", encoding="utf-8")

    js_file = root / "app.js"
    js_file.write_text("console.log(1)", encoding="utf-8")

    png_file = root / "image.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    pdf_file = root / "doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    # Kind check
    assert files.kind_for(html_file) == "text"
    assert files.kind_for(svg_file) == "image"
    assert files.kind_for(xml_file) == "text"
    assert files.kind_for(js_file) == "text"
    assert files.kind_for(png_file) == "image"
    assert files.kind_for(pdf_file) == "pdf"

    # media_type for view MUST never be html, svg or xml (prevent code execution)
    assert files.media_type(html_file, for_view=True) == "text/plain; charset=utf-8"
    assert files.media_type(svg_file, for_view=True) == "text/plain; charset=utf-8"
    assert files.media_type(xml_file, for_view=True) == "text/plain; charset=utf-8"
    assert files.media_type(js_file, for_view=True) == "text/plain; charset=utf-8"

    # Safe images and pdf return real media types
    assert files.media_type(png_file, for_view=True) == "image/png"
    assert files.media_type(pdf_file, for_view=True) == "application/pdf"

    # For download
    assert files.media_type(html_file, for_view=False) == "application/octet-stream"
    assert files.media_type(svg_file, for_view=False) == "application/octet-stream"
    assert files.media_type(png_file, for_view=False) == "image/png"
    assert files.media_type(pdf_file, for_view=False) == "application/pdf"


def test_is_binary_by_nul_byte():
    assert files.is_binary(b"Hello world\n") is False
    assert files.is_binary(b"Hello\0world\n") is True
    assert files.is_binary(b"") is False
