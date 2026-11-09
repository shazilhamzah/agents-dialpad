"""`agents-dialpad doctor`: check that everything needed is installed and ready."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import config, keepawake


@dataclass
class Check:
    level: str      # ok | warn | fail
    label: str
    detail: str = ""
    hint: str = ""


def _run(cmd: list[str], timeout: float = 15) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr or "").strip()
    return text.splitlines()[0] if text else ""


def _agent(label: str, env: str, default: str, install_hint: str) -> Check:
    exe = shutil.which(os.environ.get(env, default))
    if not exe:
        return Check("warn", label, "not found on PATH", install_hint)
    version = _run([exe, "--version"])
    return Check("ok", label, f"{version or 'found'}  ({exe})", "Make sure you are logged in: run it once in a terminal.")


def _codex_check(label: str = "Codex (codex)") -> Check:
    exe = shutil.which(os.environ.get("AG_CODEX", "codex"))
    if not exe:
        return Check("warn", label, "not found on PATH", "Install Codex CLI and log in: https://github.com/openai/codex")
    from .providers.codex import extra_args
    cmd = [exe, *extra_args("AG_CODEX_ARGS"), "login", "status"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        text = (res.stdout or res.stderr or "").strip()
        if res.returncode == 0 and "logged in" in text.lower() and "not logged in" not in text.lower():
            first_line = text.splitlines()[0] if text else ""
            account = first_line.removeprefix("Logged in using ").strip() if first_line.startswith("Logged in using ") else "ChatGPT"
            return Check("ok", label, f"signed in ({account})")
        return Check("warn", label, "not signed in", "Run `codex login` in a terminal.")
    except (OSError, subprocess.TimeoutExpired):
        return Check("warn", label, "status unknown", "Could not check login status.")


def agent_checks(cfg: dict | None = None) -> list[Check]:
    if cfg is None:
        try:
            cfg, _ = config.load()
        except Exception:
            cfg = {}
    disabled = set(cfg.get("disabled_agents", []))
    checks = []

    if "claude" in disabled:
        checks.append(Check("info", "Claude Code (claude)", "turned off in config.json"))
    else:
        checks.append(_agent("Claude Code (claude)", "AG_CLAUDE", "claude", "Install Claude Code and log in: https://claude.com/claude-code"))

    if "antigravity" in disabled:
        checks.append(Check("info", "Antigravity (agy)", "turned off in config.json"))
    else:
        checks.append(_agent("Antigravity (agy)", "AG_AGY", "agy", "Install Antigravity's CLI and log in."))

    if "codex" in disabled:
        checks.append(Check("info", "Codex (codex)", "turned off in config.json"))
    else:
        checks.append(_codex_check("Codex (codex)"))

    if all(c.level not in ("ok", "info") for c in checks):
        checks.append(Check("fail", "At least one agent CLI is required", "", "Install and log in to Claude Code, Antigravity, or Codex."))
    return checks


def tailscale_checks(port: int) -> list[Check]:
    exe = shutil.which("tailscale")
    if not exe:
        return [Check("warn", "Tailscale", "not installed", "Needed to reach this computer from your phone: https://tailscale.com")]
    out: list[Check] = []
    try:
        raw = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=15).stdout
        status = json.loads(raw)
        state = status.get("BackendState")
        dns = (status.get("Self") or {}).get("DNSName", "").rstrip(".")
        if state == "Running":
            out.append(Check("ok", "Tailscale", f"connected as {dns}"))
        else:
            out.append(Check("warn", "Tailscale", f"state is {state}", "Open the Tailscale app and sign in."))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return [Check("warn", "Tailscale", "installed, but its status could not be read")]
    try:
        serve = subprocess.run([exe, "serve", "status"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        serve = ""
    if serve and f"127.0.0.1:{port}" in serve:
        out.append(Check("ok", "Phone access (Tailscale Serve)", "published"))
    else:
        out.append(Check("warn", "Phone access (Tailscale Serve)", "not published",
                         f"Run `tailscale serve status` first, then: tailscale serve --bg --https=8443 {port}"))
    return out


def server_check(host: str, port: int) -> Check:
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::', '') else host}:{port}/api/info"
    try:
        urllib.request.urlopen(url, timeout=2)
        return Check("warn", f"Port {port}", "answering without a token?", "Something else may be using this port.")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return Check("ok", f"Port {port}", "agents-dialpad is running")
        return Check("warn", f"Port {port}", f"in use by something else (HTTP {e.code})", "Change \"port\" in config.json.")
    except OSError:
        return Check("ok", f"Port {port}", "free (not running)")


def run_checks() -> list[Check]:
    checks: list[Check] = []
    v = sys.version_info
    checks.append(Check("ok" if v >= (3, 11) else "fail", "Python", f"{v.major}.{v.minor}.{v.micro}", "" if v >= (3, 11) else "Python 3.11 or newer is required."))
    try:
        cfg, _ = config.load()
    except SystemExit as e:
        checks.append(Check("fail", "Configuration", str(e), f"Fix {config.config_path()}"))
        return checks
    except (OSError, ValueError) as e:
        checks.append(Check("fail", "Configuration", f"{type(e).__name__}: {e}", f"Fix or delete {config.config_path()}"))
        return checks
    checks.append(Check("ok", "Data folder", cfg["_data_dir"]))
    checks.append(Check("ok", "Access token", f"static, from {cfg['_token_source']}"))
    for name, path in cfg["projects"].items():
        ok = Path(path).is_dir()
        checks.append(Check("ok" if ok else "warn", f"Project '{name}'", path, "" if ok else "Folder is missing; remove it with `agents-dialpad project remove`."))
    for name in cfg.get("_invalid_projects", []):
        checks.append(Check("warn", f"Project '{name}'", "missing 'path'", "A project object in config.json must define 'path'."))
    if cfg.get("instructions_file"):
        p = config.resolve_instructions_path(cfg["instructions_file"])
        checks.append(Check("ok" if p.is_file() else "warn", "Instructions file", str(p), "" if p.is_file() else "File not found; it is ignored."))
    if not cfg.get("keep_awake", True):
        checks.append(Check("warn", "Keep awake while working", "off (keep_awake is false)"))
    elif isinstance(keepawake.default_backend(), keepawake._Noop):
        checks.append(Check("warn", "Keep awake while working", "not supported on this system"))
    else:
        checks.append(Check("ok", "Keep awake while working", "on"))
    for name, inst_file in (cfg.get("_project_instructions") or {}).items():
        p = config.resolve_instructions_path(inst_file)
        checks.append(Check("ok" if p.is_file() else "warn", f"Project '{name}' instructions", str(p), "" if p.is_file() else "File not found; it is ignored."))
    if cfg.get("allow_full_access"):
        checks.append(Check("warn", "Full access", "enabled", "Agents can run commands without asking. Only use it on projects you trust."))
    for problem in cfg.get("_quick_problems", []):
        checks.append(Check("warn", "Quick commands", problem))
    for proj_cmds in cfg.get("quick_commands", {}).values():
        for cmd in proj_cmds:
            prog = cmd["run"][0]
            if not shutil.which(prog):
                checks.append(Check("warn", f"Quick command '{cmd['label']}'", f"'{prog}' not found on PATH", f"Make sure '{prog}' is installed and on PATH."))
    if cfg.get("schedules"):
        from . import schedules
        _, problems = schedules.normalize(cfg["schedules"], cfg)
        for prob in problems:
            checks.append(Check("warn", "Schedule", prob, "Check schedules in config.json."))
    for unk in cfg.get("_unknown_disabled_agents", []):
        checks.append(Check("warn", "Disabled agent", f"unknown agent '{unk}'", "Check disabled_agents in config.json."))
    checks.extend(agent_checks(cfg))
    checks.append(server_check(cfg["host"], cfg["port"]))
    checks.extend(tailscale_checks(cfg["port"]))
    return checks
