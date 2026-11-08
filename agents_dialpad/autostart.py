"""Start agents-dialpad automatically at login: Windows (Task Scheduler), macOS (launchd), Linux (systemd --user).

Every definition points at the Python that is running this command, so install agents-dialpad somewhere permanent first
(`uv tool install` or `pipx install`), not through `uvx`, whose environment is temporary.
"""
from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

from . import config

NAME = os.environ.get("AG_AUTOSTART_NAME", "agents-dialpad")   # override only to test without touching a real install
LABEL = "io.github.shazilhamzah.agents-dialpad"


def python_for_service() -> str:
    """pythonw.exe on Windows (no console window), otherwise the running interpreter."""
    exe = Path(sys.executable)
    if os.name == "nt":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def service_args() -> list[str]:
    return ["-m", "agents_dialpad", "--data-dir", str(config.DATA), "serve", "--quiet"]


def temporary_env_warning() -> str | None:
    if "archive-v" in str(sys.executable) or "uvx" in Path(sys.executable).parts:
        return ("This Python lives in uv's temporary cache. Run `uv tool install agents-dialpad` (or pipx) first, "
                "then `agents-dialpad autostart install`.")
    return None


# ------------------------------------------------------------------ renderers (pure, unit-tested)
def render_systemd_unit(python: str, data_dir: str) -> str:
    exec_start = " ".join(shlex.quote(a) for a in [python, "-m", "agents_dialpad", "--data-dir", data_dir, "serve", "--quiet"])
    return (
        "[Unit]\n"
        "Description=agents-dialpad (chat with your coding agents from your phone)\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        f"ExecStart={exec_start}\n"
        "Restart=always\n"
        "RestartSec=5\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def render_launchd_plist(python: str, data_dir: str, log_path: str) -> str:
    plist = {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "agents_dialpad", "--data-dir", data_dir, "serve", "--quiet"],
        "RunAtLoad": True,
        "KeepAlive": True,          # launchd restarts it if it exits: this is the watchdog
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
        "ProcessType": "Background",
    }
    return plistlib.dumps(plist).decode("utf-8")


def systemd_unit_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / f"{NAME}.service"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


# ------------------------------------------------------------------ runners
def _sh(cmd: list[str], dry_run: bool, check: bool = True) -> int:
    print("  $ " + " ".join(shlex.quote(c) for c in cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd, check=False).returncode if not check else subprocess.run(cmd, check=True).returncode


def _write(path: Path, text: str, dry_run: bool) -> None:
    print(f"  write {path}")
    if dry_run:
        print("  ----\n" + "\n".join("  " + line for line in text.rstrip().splitlines()) + "\n  ----")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _windows(action: str, dry_run: bool) -> int:
    script = Path(__file__).parent / "_resources" / "windows_autostart.ps1"
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Action", action, "-Name", NAME]
    if action == "install":
        args = subprocess.list2cmdline(service_args())
        cmd += ["-Exe", python_for_service(), "-Arguments", args, "-WorkingDirectory", str(config.DATA)]
    return _sh(cmd, dry_run, check=False)


def _macos(action: str, dry_run: bool) -> int:
    plist, uid = launchd_plist_path(), os.getuid()
    target = f"gui/{uid}/{LABEL}"
    if action == "install":
        _write(plist, render_launchd_plist(python_for_service(), str(config.DATA), str(config.DATA / "gateway.log")), dry_run)
        _sh(["launchctl", "bootout", target], dry_run, check=False)     # replace a previous definition, ignore "not loaded"
        return _sh(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], dry_run, check=False)
    if action == "uninstall":
        _sh(["launchctl", "bootout", target], dry_run, check=False)
        print(f"  remove {plist}")
        if not dry_run:
            plist.unlink(missing_ok=True)
        return 0
    return _sh(["launchctl", "print", target], dry_run, check=False)


def _linux(action: str, dry_run: bool) -> int:
    unit = systemd_unit_path()
    if action == "install":
        _write(unit, render_systemd_unit(python_for_service(), str(config.DATA)), dry_run)
        _sh(["systemctl", "--user", "daemon-reload"], dry_run, check=False)
        rc = _sh(["systemctl", "--user", "enable", "--now", f"{NAME}.service"], dry_run, check=False)
        print("  Tip: to keep it running when you are not logged in, run: loginctl enable-linger $USER")
        return rc
    if action == "uninstall":
        _sh(["systemctl", "--user", "disable", "--now", f"{NAME}.service"], dry_run, check=False)
        print(f"  remove {unit}")
        if not dry_run:
            unit.unlink(missing_ok=True)
        return _sh(["systemctl", "--user", "daemon-reload"], dry_run, check=False)
    return _sh(["systemctl", "--user", "status", f"{NAME}.service", "--no-pager"], dry_run, check=False)


def run(action: str, dry_run: bool = False) -> int:
    warn = temporary_env_warning()
    if warn and action == "install":
        print("WARNING: " + warn)
    config.ensure_data_dir()
    print(f"autostart {action}{' (dry run)' if dry_run else ''}:")
    if os.name == "nt":
        return _windows(action, dry_run)
    if sys.platform == "darwin":
        return _macos(action, dry_run)
    return _linux(action, dry_run)
