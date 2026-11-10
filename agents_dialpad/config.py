"""Configuration, data directory and the access token."""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
from pathlib import Path

APP_NAME = "agents-dialpad"
PKG = Path(__file__).resolve().parent          # the installed package (holds static/ and instructions/)
ROOT = PKG.parent                              # the repo root, when running from a git checkout
MIN_TOKEN_LEN = 16
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-\[\]/]{0,100}$")


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


def scan_documents_projects(extra_dirs: list[str] | None = None) -> dict[str, str]:
    dirs_to_scan = [Path.home() / "Documents"] if extra_dirs is None else [Path(d).expanduser().resolve() for d in extra_dirs]
    out: dict[str, str] = {}
    for parent in dirs_to_scan:
        if not parent.is_dir():
            continue
        try:
            for p in parent.iterdir():
                try:
                    if not p.is_dir():
                        continue
                    name = p.name
                    if name.startswith((".", "$")):
                        continue
                    if name in ("My Music", "My Pictures", "My Videos"):
                        continue
                    p_resolved = p.resolve()
                    if not p_resolved.is_dir():
                        continue
                    out[name] = str(p_resolved)
                except (PermissionError, OSError):
                    continue
        except Exception:
            continue
    return out


def refresh_projects(cfg: dict) -> dict[str, str]:
    """Refresh cfg["projects"] with scanned folders if scan_documents or scan_dirs is enabled."""
    scan_docs = cfg.get("scan_documents", False)
    scan_dirs = cfg.get("scan_dirs", [])
    if not scan_docs and not scan_dirs:
        return cfg.get("projects", {})

    target_dirs = []
    if scan_docs:
        target_dirs.append(Path.home() / "Documents")
    if isinstance(scan_dirs, list):
        for d in scan_dirs:
            if isinstance(d, str) and d.strip():
                target_dirs.append(Path(d).expanduser().resolve())

    scanned = scan_documents_projects(extra_dirs=[str(d) for d in target_dirs])
    projects = cfg.setdefault("projects", {})
    existing_lower = {k.lower(): k for k in projects}
    existing_paths = {Path(v).resolve(): k for k, v in projects.items()}
    for name, path in scanned.items():
        if name not in projects and name.lower() not in existing_lower and Path(path).resolve() not in existing_paths:
            projects[name] = path
    return projects


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
    raw_projects = cfg.get("projects") or {}
    norm_projects: dict[str, str] = {}
    proj_instructions: dict[str, str] = {}
    invalid_projects: list[str] = []

    for name, val in raw_projects.items():
        if isinstance(val, dict):
            raw_path = val.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                invalid_projects.append(name)
                continue
            p = Path(raw_path)
            norm_projects[name] = str(p if p.is_absolute() else DATA / p)
            inst = val.get("instructions_file")
            if inst and isinstance(inst, str) and inst.strip():
                proj_instructions[name] = inst.strip()
        elif isinstance(val, str):
            p = Path(val)
            norm_projects[name] = str(p if p.is_absolute() else DATA / p)
        else:
            invalid_projects.append(name)

    cfg["projects"] = norm_projects
    cfg["_project_instructions"] = proj_instructions
    cfg["_invalid_projects"] = invalid_projects
    cfg.setdefault("scan_documents", False)
    cfg.setdefault("scan_dirs", [])
    if cfg.get("scan_documents") or cfg.get("scan_dirs"):
        refresh_projects(cfg)
    # Optional text file added to every conversation (none by default). Example: "instructions/caveman.md".
    cfg.setdefault("instructions_file", None)
    cfg.setdefault("keep_awake", True)
    cfg.setdefault("approval_timeout_seconds", 600)
    if "AG_APPROVAL_TIMEOUT" in os.environ:
        try:
            cfg["approval_timeout_seconds"] = float(os.environ["AG_APPROVAL_TIMEOUT"])
        except ValueError:
            pass
    cfg.setdefault("push_show_titles", False)
    cfg.setdefault("push_show_commands", False)
    cfg.setdefault("push_contact", "mailto:agents-dialpad@example.com")
    from . import quick
    cfg["quick_commands"], cfg["_quick_problems"] = quick.normalize(cfg.get("quick_commands"))
    # Extra models to offer for Codex (empty by default: offers "Default").
    cfg.setdefault("codex_models", [])
    cfg.setdefault("codex_default_model", "")
    if not isinstance(cfg["codex_default_model"], str) or (cfg["codex_default_model"] and not MODEL_RE.match(cfg["codex_default_model"])):
        cfg["codex_default_model"] = ""

    cfg.setdefault("disabled_agents", [])
    if not isinstance(cfg["disabled_agents"], list):
        cfg["disabled_agents"] = []
    from .providers import PROVIDERS, PLANNED
    known_agents = set(PROVIDERS.keys()) | {p["name"] for p in PLANNED}
    valid_disabled = []
    unknown_disabled = []
    for a in cfg["disabled_agents"]:
        if isinstance(a, str):
            if a in known_agents:
                valid_disabled.append(a)
            else:
                unknown_disabled.append(a)
    cfg["disabled_agents"] = valid_disabled
    cfg["_unknown_disabled_agents"] = unknown_disabled

    # Threshold for low-subscription alerts (percentage). 0 disables.
    cfg.setdefault("limit_alert_percent", 20)
    cfg.setdefault("app_lock_idle_minutes", 5)
    # Scheduled prompts to run at specific times (empty by default).
    cfg.setdefault("schedules", [])

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


def read_instructions(cfg: dict, project: str | None = None) -> str:
    """Read fresh on every turn so edits apply without a restart."""
    parts = []
    global_file = cfg.get("instructions_file")
    if global_file:
        try:
            txt = resolve_instructions_path(global_file).read_text(encoding="utf-8").strip()
            if txt:
                parts.append(txt)
        except OSError:
            pass

    if project:
        proj_inst = (cfg.get("_project_instructions") or {}).get(project)
        if proj_inst:
            try:
                txt = resolve_instructions_path(proj_inst).read_text(encoding="utf-8").strip()
                if txt:
                    parts.append(txt)
            except OSError:
                pass

    return "\n\n".join(parts)
