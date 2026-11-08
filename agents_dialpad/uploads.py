"""Attachment uploads for chats."""
from __future__ import annotations

import os
import re
import secrets
import shutil
from pathlib import Path
from fastapi import HTTPException

from . import config

MAX_FILE = 15 * 1024 * 1024          # 15 MB
MAX_CHAT_TOTAL = 200 * 1024 * 1024  # 200 MB
ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp", "heic", "pdf",
    "txt", "md", "csv", "json", "log", "yaml", "yml", "xml",
    "html", "css", "js", "ts", "py",
}


def upload_dir(chat_id: str) -> Path:
    return config.DATA / "uploads" / chat_id


def safe_name(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    clean_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")
    clean_ext = re.sub(r"[^A-Za-z0-9.]+", "", ext).lower()
    if not clean_stem:
        clean_stem = "file"
    max_stem_len = max(1, 80 - len(clean_ext))
    clean_stem = clean_stem[:max_stem_len].rstrip("-.") or "file"
    return clean_stem + clean_ext


def save(chat_id: str, name: str, data: bytes) -> dict:
    sname = safe_name(name)
    ext = os.path.splitext(sname)[1].lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Files with extension .{ext} are not allowed")

    if len(data) > MAX_FILE:
        raise HTTPException(413, "That file is larger than 15 MB")

    udir = upload_dir(chat_id)
    udir.mkdir(parents=True, exist_ok=True)

    current_total = sum(f.stat().st_size for f in udir.glob("*") if f.is_file())
    if current_total + len(data) > MAX_CHAT_TOTAL:
        raise HTTPException(413, "Chat upload limit exceeded (200 MB max)")

    prefix = secrets.token_hex(4)
    stored_name = f"{prefix}-{sname}"
    dest = udir / stored_name
    dest.write_bytes(data)
    return {"name": stored_name, "size": len(data)}


def resolve(chat_id: str, names: list[str]) -> list[Path]:
    udir = upload_dir(chat_id).resolve()
    paths: list[Path] = []
    for name in names:
        if not isinstance(name, str) or not name or "\0" in name or "/" in name or "\\" in name or name in ("..", "."):
            raise ValueError(f"Invalid attachment name: {name}")
        p = (udir / name).resolve()
        try:
            if not p.is_relative_to(udir) or not p.is_file():
                raise ValueError(f"Attachment not found: {name}")
        except (ValueError, AttributeError):
            raise ValueError(f"Attachment not found: {name}")
        paths.append(p)
    return paths


def remove_all(chat_id: str) -> None:
    udir = upload_dir(chat_id)
    if udir.exists():
        shutil.rmtree(udir, ignore_errors=True)
