"""Configuration, data directory and the access token."""
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

APP_NAME = "agents-dialpad"
PKG = Path(__file__).resolve().parent          # the installed package (holds static/ and instructions/)
ROOT = PKG.parent                              # the repo root, when running from a git checkout
MIN_TOKEN_LEN = 16


def is_source_checkout() -> bool:
    return (ROOT / "pyproject.toml").exists() and (ROOT / "agents_dialpad").is_dir()


def platform_data_dir(plat: str | None = None) -> Path:
    """Where an installed copy keeps its config, token and chats (per user). `plat` is for tests."""
    plat = plat or ("windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux")
    if plat == "windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif plat == "macos":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def default_data_dir() -> Path:
    """AG_DATA wins. A git checkout keeps data next to the code (./data); an installed copy uses the user data dir."""
    env = os.environ.get("AG_DATA")
    if env:
        return Path(env)
    return ROOT / "data" if is_source_checkout() else platform_data_dir()


DATA = default_data_dir()
STATIC = Path(os.environ.get("AG_STATIC") or PKG / "static")  # AG_STATIC: serve a UI copy while developing


def config_path() -> Path:
    return DATA / "config.json"


def ensure_data_dir() -> Path:
    """Create the data dir, config.json (first run only) and the default workspace folder."""
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "chats").mkdir(exist_ok=True)
    (DATA / "workspace").mkdir(exist_ok=True)
    if not config_path().exists():
        save_raw({
            "host": "127.0.0.1",
            "port": 8787,
            # name -> folder. The phone can only pick from this list, never type a path.
            # Relative paths are relative to this data folder.
            "projects": {"workspace": "workspace"},
        })
    return DATA


def read_raw() -> dict:
    """The config exactly as written in config.json (no defaults applied, paths unresolved)."""
    ensure_data_dir()
    return json.loads(config_path().read_text(encoding="utf-8-sig"))  # tolerate a BOM from Windows editors


def save_raw(raw: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = config_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, config_path())


def load() -> tuple[dict, str]:
    """Return (config, token). Creates the data dir, config.json and token.txt on first run.

    The token never changes between runs unless you change it:
      1. env var AG_TOKEN, else
      2. "token" in config.json, else
      3. token.txt in the data dir (generated once, then reused forever)
    """
    cfg = read_raw()
    cfg.setdefault("host", "127.0.0.1")
    cfg.setdefault("port", 8787)
    cfg.setdefault("projects", {"workspace": "workspace"})
    # Relative project paths are relative to the data folder, so moving it doesn't break them.
    cfg["projects"] = {name: str(p if (p := Path(raw)).is_absolute() else DATA / p) for name, raw in cfg["projects"].items()}
    # Optional text file added to every conversation (none by default). Example: "instructions/caveman.md".
    cfg.setdefault("instructions_file", None)
    cfg.setdefault("keep_awake", True)
    from . import quick
    cfg["quick_commands"], cfg["_quick_problems"] = quick.normalize(cfg.get("quick_commands"))

    token = os.environ.get("AG_TOKEN") or cfg.get("token")
    if token:
        source = "AG_TOKEN env var" if os.environ.get("AG_TOKEN") else "config.json"
        if len(token) < MIN_TOKEN_LEN:
            raise SystemExit(f"Token from {source} is too short (minimum {MIN_TOKEN_LEN} characters).")
    else:
        token_path = DATA / "token.txt"
        if not token_path.exists():
            token_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        token, source = token_path.read_text(encoding="utf-8").strip(), "token.txt"
    cfg["_token_source"] = source
    cfg["_data_dir"] = str(DATA)
    return cfg, token


def rotate_token() -> str:
    """Replace token.txt with a fresh random token."""
    ensure_data_dir()
    token = secrets.token_urlsafe(32)
    (DATA / "token.txt").write_text(token, encoding="utf-8")
    return token


def resolve_instructions_path(name: str) -> Path:
    """Absolute path as-is; otherwise look in the data folder, then in the examples shipped with the package."""
    p = Path(name)
    if p.is_absolute():
        return p
    for base in (DATA, PKG):
        if (base / p).exists():
            return base / p
    return DATA / p


def read_instructions(cfg: dict) -> str:
    """Read fresh on every turn so edits apply without a restart."""
    name = cfg.get("instructions_file")
    if not name:
        return ""
    try:
        return resolve_instructions_path(name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
