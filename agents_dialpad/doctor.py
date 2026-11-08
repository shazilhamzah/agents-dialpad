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


def agent_checks() -> list[Check]:
    checks = [
        _agent("Claude Code (claude)", "AG_CLAUDE", "claude", "Install Claude Code and log in: https://claude.com/claude-code"),
        _agent("Antigravity (agy)", "AG_AGY", "agy", "Install Antigravity's CLI and log in."),
    ]
    if all(c.level != "ok" for c in checks):
        checks.append(Check("fail", "At least one agent CLI is required", "", "Install and log in to Claude Code and/or Antigravity."))
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
    if cfg.get("instructions_file"):
        p = config.resolve_instructions_path(cfg["instructions_file"])
        checks.append(Check("ok" if p.is_file() else "warn", "Instructions file", str(p), "" if p.is_file() else "File not found; it is ignored."))
    if not cfg.get("keep_awake", True):
        checks.append(Check("warn", "Keep awake while working", "off (keep_awake is false)"))
    elif isinstance(keepawake.default_backend(), keepawake._Noop):
        checks.append(Check("warn", "Keep awake while working", "not supported on this system"))
    else:
        checks.append(Check("ok", "Keep awake while working", "on"))
    if cfg.get("allow_full_access"):
        checks.append(Check("warn", "Full access", "enabled", "Agents can run commands without asking. Only use it on projects you trust."))
    for problem in cfg.get("_quick_problems", []):
        checks.append(Check("warn", "Quick commands", problem))
    for proj_cmds in cfg.get("quick_commands", {}).values():
        for cmd in proj_cmds:
            prog = cmd["run"][0]
            if not shutil.which(prog):
                checks.append(Check("warn", f"Quick command '{cmd['label']}'", f"'{prog}' not found on PATH", f"Make sure '{prog}' is installed and on PATH."))
    checks.extend(agent_checks())
    checks.append(server_check(cfg["host"], cfg["port"]))
    checks.extend(tailscale_checks(cfg["port"]))
    return checks
