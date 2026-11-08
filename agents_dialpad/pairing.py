"""Build the link a phone should open, and render it as a QR code."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys


def serve_url_from_status(status: dict, port: int) -> str | None:
    """Find the https URL that Tailscale Serve maps to our local port. Pure function: unit-tested."""
    targets = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    for hostport, conf in (status.get("Web") or {}).items():
        proxy = (((conf or {}).get("Handlers") or {}).get("/") or {}).get("Proxy", "")
        if proxy.rstrip("/") in targets and ":" in hostport:
            host, p = hostport.rsplit(":", 1)
            return f"https://{host}" + ("" if p == "443" else f":{p}") + "/"
    return None


def tailscale_url(port: int) -> str | None:
    exe = shutil.which("tailscale")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "serve", "status", "--json"], capture_output=True, text=True, timeout=10).stdout
        return serve_url_from_status(json.loads(out or "{}"), port)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def pair_link(base_url: str, token: str) -> str:
    return base_url.rstrip("/") + "/#token=" + token


def qr_svg_data_uri(text: str) -> str:
    import segno
    return segno.make(text, error="m").svg_data_uri(scale=6, border=2, dark="#000", light="#fff")


def qr_png(text: str, path: str) -> None:
    import segno
    segno.make(text, error="m").save(path, scale=8, border=4)


def qr_terminal(text: str) -> None:
    import segno
    q = segno.make(text, error="m")
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to a code page without block characters
    except (AttributeError, ValueError):
        pass
    try:
        q.terminal(compact=True)
    except UnicodeEncodeError:
        q.terminal()
