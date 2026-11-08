"""Configuration, data directory and the access token."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("AG_DATA") or ROOT / "data")
STATIC = Path(os.environ.get("AG_STATIC") or ROOT / "static")  # AG_STATIC: serve a UI copy while developing
MIN_TOKEN_LEN = 16


def load() -> tuple[dict, str]:
    """Return (config, token). Creates the data dir, config.json and token.txt on first run.

    The token never changes between runs unless you change it:
      1. env var AG_TOKEN, else
      2. "token" in data/config.json, else
      3. data/token.txt (generated once, then reused forever)
    """
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "chats").mkdir(exist_ok=True)
    workspace = DATA / "workspace"
    workspace.mkdir(exist_ok=True)

    cfg_path = DATA / "config.json"
    if not cfg_path.exists():
        cfg_path.write_text(
            json.dumps(
                {
                    "host": "127.0.0.1",
                    "port": 8787,
                    # name -> folder. The phone can only pick from this list, never type a path.
                    "projects": {"workspace": str(workspace)},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))  # tolerate a BOM from Windows editors
    cfg.setdefault("host", "127.0.0.1")
    cfg.setdefault("port", 8787)
    cfg.setdefault("projects", {"workspace": str(workspace)})
    # Relative project paths are relative to the agents-dialpad folder, so moving the folder doesn't break them.
    cfg["projects"] = {name: str(p if (p := Path(raw)).is_absolute() else ROOT / p) for name, raw in cfg["projects"].items()}
    # Optional text file added to every conversation (none by default). Example: "instructions/caveman.md".
    cfg.setdefault("instructions_file", None)

    token = os.environ.get("AG_TOKEN") or cfg.get("token")
    if token:
        source = "AG_TOKEN env var" if os.environ.get("AG_TOKEN") else "config.json"
        if len(token) < MIN_TOKEN_LEN:
            raise SystemExit(f"Token from {source} is too short (minimum {MIN_TOKEN_LEN} characters).")
    else:
        token_path = DATA / "token.txt"
        if not token_path.exists():
            token_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        token, source = token_path.read_text(encoding="utf-8").strip(), "data/token.txt"
    cfg["_token_source"] = source
    return cfg, token


def read_instructions(cfg: dict) -> str:
    """Read fresh on every turn so edits apply without a restart."""
    name = cfg.get("instructions_file")
    if not name:
        return ""
    path = Path(name)
    if not path.is_absolute():
        path = ROOT / path
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
