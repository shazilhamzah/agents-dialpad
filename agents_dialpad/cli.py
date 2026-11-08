"""Command line interface: `agents-dialpad <command>` (or `python -m agents_dialpad <command>`)."""
from __future__ import annotations

import argparse
import os
import re
import socket
import sys
from pathlib import Path

from . import __version__, config

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


def port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def local_url(cfg: dict, token: str | None = None) -> str:
    host = cfg["host"] if cfg["host"] not in ("0.0.0.0", "::", "") else "127.0.0.1"
    return f"http://{host}:{cfg['port']}/" + (f"#token={token}" if token else "")


def ensure_stdio() -> None:
    """pythonw (no console) has no stdout/stderr; send them to a log file so logging cannot crash."""
    if sys.stdout is None or sys.stderr is None:
        config.DATA.mkdir(parents=True, exist_ok=True)
        log = open(config.DATA / "gateway.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


# ------------------------------------------------------------------ serve
def cmd_serve(args) -> int:
    cfg, token = config.load()
    host, port = args.host or cfg["host"], args.port or cfg["port"]
    probe = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    if port_open(probe, port):
        print(f"agents-dialpad is already running on port {port}.")
        return 0
    ensure_stdio()
    cfg = {**cfg, "host": host, "port": port}
    interactive = bool(sys.stdout and sys.stdout.isatty()) and not args.quiet
    print(f"\nagents-dialpad {__version__}")
    if interactive:
        print(f"  Open      : {local_url(cfg, token)}")
        print("  (open the link once per device; the token is saved in the browser and removed from the address bar)")
    else:
        print(f"  Listening : {local_url(cfg)}   (token: run `agents-dialpad token`)")
    print(f"  Token     : static, from {cfg['_token_source']}")
    print(f"  Data      : {cfg['_data_dir']}")
    print(f"  Projects  : {', '.join(f'{k} -> {v}' for k, v in cfg['projects'].items())}")
    print(f"  Instructions: {cfg.get('instructions_file') or 'none'}")
    if cfg.get("allow_full_access"):
        print("  NOTICE    : Full access is ENABLED: agents can run commands without asking.")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  WARNING   : listening on {host}; anyone who can reach this port and has the token can run agents here.")
    print()
    import uvicorn

    from .app import create_app

    # No reload: on Windows it swaps the event loop and breaks subprocess handling.
    uvicorn.run(create_app(cfg, token), host=host, port=port, log_level="info")
    return 0


# ------------------------------------------------------------------ projects
def add_project(name: str, path: str) -> str:
    if not NAME_RE.match(name):
        raise SystemExit(f"Invalid project name '{name}': use letters, digits, '.', '_' or '-' (max 40).")
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise SystemExit(f"Not a folder: {folder}")
    raw = config.read_raw()
    raw.setdefault("projects", {})[name] = str(folder)
    config.save_raw(raw)
    return f"Added project '{name}' -> {folder}"


def cmd_project(args) -> int:
    if args.action == "add":
        print(add_project(args.name, args.path))
    elif args.action == "remove":
        raw = config.read_raw()
        if args.name not in raw.get("projects", {}):
            raise SystemExit(f"No project named '{args.name}'.")
        del raw["projects"][args.name]
        config.save_raw(raw)
        print(f"Removed project '{args.name}'.")
    else:
        cfg, _ = config.load()
        for name, path in cfg["projects"].items():
            print(f"{'ok ' if Path(path).is_dir() else 'MISSING'}  {name:<20} {path}")
    if args.action in ("add", "remove"):
        print("Restart agents-dialpad for the change to take effect.")
    return 0


# ------------------------------------------------------------------ init
def cmd_init(args) -> int:
    config.ensure_data_dir()
    for spec in args.project or []:
        name, sep, path = spec.partition("=")
        if not sep:
            raise SystemExit(f"--project expects NAME=PATH, got '{spec}'")
        print(add_project(name.strip(), path.strip()))
    if not args.project and not args.yes and sys.stdin.isatty():
        print("Add project folders the phone may use (leave the path empty to finish).")
        while True:
            path = input("  Project folder path: ").strip()
            if not path:
                break
            default = re.sub(r"[^A-Za-z0-9._-]", "-", Path(path).expanduser().name)[:40] or "project"
            name = input(f"  Name [{default}]: ").strip() or default
            try:
                print("  " + add_project(name, path))
            except SystemExit as e:
                print(f"  {e}")
    cfg, token = config.load()
    print(f"\nReady. Data folder: {cfg['_data_dir']}")
    print("Projects: " + ", ".join(cfg["projects"]))
    print("\nNext steps:\n  1. agents-dialpad doctor      check that your agent CLIs and Tailscale are ready"
          "\n  2. agents-dialpad serve       start it, then open the link it prints"
          "\n  3. agents-dialpad autostart install    (optional) start it automatically at login")
    return 0


# ------------------------------------------------------------------ token / pair
def cmd_token(args) -> int:
    if args.rotate:
        raw = config.read_raw()
        if os.environ.get("AG_TOKEN") or raw.get("token"):
            raise SystemExit("The token is set by AG_TOKEN or by \"token\" in config.json; change it there.")
        config.rotate_token()
        print("Token rotated. Restart agents-dialpad and re-open the link on each device.")
    cfg, token = config.load()
    print(token)
    if not args.quiet:
        print(f"\nLink for this computer : {local_url(cfg, token)}")
        print("For your phone         : https://<your-machine>.<your-tailnet>.ts.net:8443/#token=" + token)
    return 0


def cmd_pair(args) -> int:
    from . import pairing

    cfg, token = config.load()
    local = local_url(cfg)
    base = args.url or pairing.tailscale_url(cfg["port"]) or local
    remote = base != local
    link = pairing.pair_link(base, token)
    print("Anyone who scans this code can use your agents. Do not share or screenshot it.")
    if not remote:
        print("Phone access is not published, so this link only works on this computer. See docs/remote-access.md.")
    if not args.no_qr:
        pairing.qr_terminal(link)
    if args.png:
        pairing.qr_png(link, args.png)
        print(f"Saved {args.png}")
    print(link)
    return 0


# ------------------------------------------------------------------ doctor / autostart
def cmd_doctor(args) -> int:
    from .doctor import run_checks

    marks = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
    worst = "ok"
    for c in run_checks():
        print(f"[{marks[c.level]}] {c.label}" + (f": {c.detail}" if c.detail else ""))
        if c.hint:
            print(f"       {c.hint}")
        if c.level == "fail" or (c.level == "warn" and worst == "ok"):
            worst = c.level
    print("\nAll good." if worst == "ok" else "\nSome checks need attention." if worst == "warn" else "\nFix the FAIL items above.")
    return 1 if worst == "fail" else 0


def cmd_autostart(args) -> int:
    from . import autostart

    return autostart.run(args.action, dry_run=args.dry_run)


# ------------------------------------------------------------------ entry point
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agents-dialpad", description="Chat with the AI coding CLIs on this computer from your phone.")
    p.add_argument("--version", action="version", version=f"agents-dialpad {__version__}")
    p.add_argument("--data-dir", help="where config, token and chats live (default: per-user data folder, or ./data in a checkout)")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="start the server (default command)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--quiet", action="store_true", help="never print the access token (used by background services)")
    s.set_defaults(func=cmd_serve)

    i = sub.add_parser("init", help="create the data folder and choose project folders")
    i.add_argument("--project", action="append", metavar="NAME=PATH", help="add a project (repeatable)")
    i.add_argument("--yes", action="store_true", help="never prompt")
    i.set_defaults(func=cmd_init)

    pr = sub.add_parser("project", help="manage the project folders the phone can pick")
    pr.add_argument("action", choices=["add", "list", "remove"])
    pr.add_argument("name", nargs="?")
    pr.add_argument("path", nargs="?")
    pr.set_defaults(func=cmd_project)

    t = sub.add_parser("token", help="show (or rotate) the access token")
    t.add_argument("--rotate", action="store_true")
    t.add_argument("--quiet", action="store_true", help="print only the token")
    t.set_defaults(func=cmd_token)

    pa = sub.add_parser("pair", help="print a QR code and link to connect a phone")
    pa.add_argument("--url", help="override the detected base URL")
    pa.add_argument("--png", metavar="FILE", help="also save the QR code as a PNG file")
    pa.add_argument("--no-qr", action="store_true", help="print only the link, no terminal QR")
    pa.set_defaults(func=cmd_pair)

    d = sub.add_parser("doctor", help="check that everything needed is installed and ready")
    d.set_defaults(func=cmd_doctor)

    a = sub.add_parser("autostart", help="start automatically at login (Windows, macOS, Linux)")
    a.add_argument("action", choices=["install", "uninstall", "status"])
    a.add_argument("--dry-run", action="store_true", help="show what would be written, change nothing")
    a.set_defaults(func=cmd_autostart)
    return p


COMMANDS = {"serve", "init", "project", "token", "pair", "doctor", "autostart"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not COMMANDS.intersection(argv) and not {"--version", "-h", "--help"}.intersection(argv):
        argv.append("serve")                       # plain `agents-dialpad` starts the server
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.data_dir:
        os.environ["AG_DATA"] = args.data_dir
        config.DATA = Path(args.data_dir)
    if args.command == "project" and args.action in ("add", "remove") and not args.name:
        parser.error(f"project {args.action} needs a NAME" + (" and PATH" if args.action == "add" else ""))
    if args.command == "project" and args.action == "add" and not args.path:
        parser.error("project add needs NAME and PATH")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
