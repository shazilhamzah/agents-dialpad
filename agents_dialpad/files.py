"""File operations for project browsing and viewing."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

MAX_LIST = 1000
MAX_TEXT = 1_048_576
MAX_PREVIEW = 50 * 1024 * 1024

DENY_GLOBS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "*.kdbx",
    ".npmrc",
    ".pypirc",
    "credentials*",
    ".netrc",
)
ALLOW_DESPITE_DENY = (".env.example", ".env.sample", "*.pub")

RESERVED_NAMES = frozenset({
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})

IMAGE_EXTENSIONS = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".ico",
    ".heic",
    ".heif",
    ".tiff",
    ".tif",
})

TEXT_EXTENSIONS = frozenset({
    ".txt",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".htm",
    ".xhtml",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".kts",
    ".rb",
    ".php",
    ".sql",
    ".log",
    ".diff",
    ".patch",
    ".dockerfile",
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    ".env.example",
    ".env.sample",
})

VIEW_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pdf": "application/pdf",
    # Script/markup/SVG types served as text/plain to prevent script execution
    ".html": "text/plain; charset=utf-8",
    ".htm": "text/plain; charset=utf-8",
    ".xhtml": "text/plain; charset=utf-8",
    ".svg": "text/plain; charset=utf-8",
    ".xml": "text/plain; charset=utf-8",
    ".js": "text/plain; charset=utf-8",
    ".mjs": "text/plain; charset=utf-8",
}

DOWNLOAD_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".pdf": "application/pdf",
}


def is_binary(head: bytes) -> bool:
    """Return True if head contains a NUL byte."""
    return b"\0" in head


def kind_for(path: Path) -> str:
    """Return the viewer kind: 'image' | 'pdf' | 'markdown' | 'json' | 'csv' | 'text' | 'binary'."""
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in (".md", ".markdown", ".mdown", ".mkdn"):
        return "markdown"
    if suffix == ".json":
        return "json"
    if suffix in (".csv", ".tsv"):
        return "csv"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in TEXT_EXTENSIONS or name in ("dockerfile", "makefile", "license", "authors"):
        return "text"
    if path.is_file():
        try:
            with path.open("rb") as f:
                chunk = f.read(8192)
            if is_binary(chunk):
                return "binary"
            return "text"
        except (OSError, PermissionError):
            pass
    return "binary"


def media_type(path: Path, *, for_view: bool) -> str:
    """Return the Content-Type header value based on fixed allow-map."""
    suffix = path.suffix.lower()
    if for_view:
        if suffix in VIEW_MEDIA_TYPES:
            return VIEW_MEDIA_TYPES[suffix]
        k = kind_for(path)
        if k in ("text", "markdown", "json", "csv"):
            return "text/plain; charset=utf-8"
        return "application/octet-stream"
    else:
        if suffix in DOWNLOAD_MEDIA_TYPES:
            return DOWNLOAD_MEDIA_TYPES[suffix]
        return "application/octet-stream"


def is_denied(name: str, extra_deny: tuple[str, ...] = ()) -> bool:
    """Check if filename matches the secrets denylist unless explicitly allowed."""
    name_lower = name.lower()
    for allow_pattern in ALLOW_DESPITE_DENY:
        if fnmatch.fnmatch(name_lower, allow_pattern.lower()):
            return False
    all_deny = DENY_GLOBS + tuple(extra_deny)
    for deny_pattern in all_deny:
        if fnmatch.fnmatch(name_lower, deny_pattern.lower()):
            return True
    return False


def resolve(
    root: Path,
    rel: str,
    *,
    data_dir: Path,
    extra_deny: tuple[str, ...] = (),
    allow_root: bool = False,
) -> Path:
    """Validate a client path and return the real resolved path.

    Raises:
        ValueError: for bad syntax / traversal input (maps to 400).
        FileNotFoundError: for anything denied or missing (maps to 404).
    """
    if not isinstance(rel, str):
        raise ValueError("Invalid path: must be a string")
    if "\0" in rel:
        raise ValueError("Invalid path: contains NUL byte")

    clean_rel = rel.replace("\\", "/")

    if clean_rel == "" or clean_rel == ".":
        if not allow_root:
            raise ValueError("Target cannot be root directory")
        target_candidate = root
    else:
        if clean_rel.startswith("/") or rel.startswith(("\\\\", "//")):
            raise ValueError("Absolute path not allowed")
        if len(rel) >= 2 and rel[1] == ":":
            raise ValueError("Absolute path with drive letter not allowed")
        p_obj = Path(rel)
        if p_obj.is_absolute():
            raise ValueError("Absolute path not allowed")

        segments = clean_rel.split("/")
        for seg in segments:
            if seg in ("..", ".", ""):
                raise ValueError(f"Invalid path segment '{seg}'")
            if ":" in seg:
                raise ValueError(f"Invalid path segment '{seg}': contains ':'")
            if seg.endswith((".", " ")):
                raise ValueError(f"Invalid path segment '{seg}': trailing dot or space not allowed")

            stem = seg.split(".")[0].upper()
            if stem in RESERVED_NAMES:
                raise ValueError(f"Invalid path segment '{seg}': reserved device name")

        target_candidate = root / clean_rel

    try:
        resolved_root = root.resolve()
        resolved_data = data_dir.resolve()
        resolved_target = target_candidate.resolve()
    except OSError:
        raise FileNotFoundError("File not found")

    norm_root = os.path.normcase(str(resolved_root))
    norm_target = os.path.normcase(str(resolved_target))
    norm_data = os.path.normcase(str(resolved_data))

    norm_root_path = Path(norm_root)
    norm_target_path = Path(norm_target)
    norm_data_path = Path(norm_data)

    try:
        if not (norm_target_path == norm_root_path or norm_target_path.is_relative_to(norm_root_path)):
            raise FileNotFoundError("File not found")
    except (ValueError, AttributeError):
        raise FileNotFoundError("File not found")

    if not allow_root and norm_target_path == norm_root_path:
        raise ValueError("Target cannot be root directory")

    if norm_root_path == norm_data_path:
        raise FileNotFoundError("File not found")

    if not norm_root_path.is_relative_to(norm_data_path):
        try:
            if norm_target_path == norm_data_path or norm_target_path.is_relative_to(norm_data_path):
                raise FileNotFoundError("File not found")
        except (ValueError, AttributeError):
            raise FileNotFoundError("File not found")

    rel_to_root = norm_target_path.relative_to(norm_root_path)
    if any(part.lower() == ".git" for part in rel_to_root.parts):
        raise FileNotFoundError("File not found")

    for part in rel_to_root.parts:
        if is_denied(part, extra_deny):
            raise FileNotFoundError("File not found")

    if not resolved_target.exists():
        raise FileNotFoundError("File not found")

    return resolved_target


def list_dir(
    root: Path,
    rel: str = "",
    *,
    data_dir: Path,
    extra_deny: tuple[str, ...] = (),
) -> dict[str, Any]:
    """List directory entries for project browsing."""
    folder = resolve(root, rel, data_dir=data_dir, extra_deny=extra_deny, allow_root=True)
    if not folder.is_dir():
        raise ValueError(f"'{rel}' is not a directory")

    resolved_root = root.resolve()
    resolved_data = data_dir.resolve()
    norm_root = Path(os.path.normcase(str(resolved_root)))
    norm_data = Path(os.path.normcase(str(resolved_data)))

    dir_entries: list[dict[str, Any]] = []
    file_entries: list[dict[str, Any]] = []

    try:
        with os.scandir(folder) as it:
            for entry in it:
                name = entry.name
                if name.lower() == ".git":
                    continue
                if is_denied(name, extra_deny):
                    continue

                try:
                    entry_path = Path(entry.path)
                    entry_res = entry_path.resolve()
                    norm_entry = Path(os.path.normcase(str(entry_res)))

                    # Do not follow symlinks leaving root or entering data_dir
                    if not (norm_entry == norm_root or norm_entry.is_relative_to(norm_root)):
                        continue
                    if not norm_root.is_relative_to(norm_data):
                        if norm_entry == norm_data or norm_entry.is_relative_to(norm_data):
                            continue

                    st = entry.stat()
                except (OSError, PermissionError):
                    continue

                if entry.is_dir(follow_symlinks=True):
                    dir_entries.append({
                        "name": name,
                        "kind": "dir",
                        "size": 0,
                        "mtime": int(st.st_mtime),
                        "type": "dir",
                    })
                else:
                    k = kind_for(entry_path)
                    file_entries.append({
                        "name": name,
                        "kind": "file",
                        "size": st.st_size,
                        "mtime": int(st.st_mtime),
                        "type": k,
                    })
    except OSError as e:
        raise FileNotFoundError("Directory not found") from e

    dir_entries.sort(key=lambda x: x["name"].lower())
    file_entries.sort(key=lambda x: x["name"].lower())

    all_entries = dir_entries + file_entries
    truncated = len(all_entries) > MAX_LIST
    if truncated:
        all_entries = all_entries[:MAX_LIST]

    return {
        "path": rel,
        "entries": all_entries,
        "truncated": truncated,
    }
