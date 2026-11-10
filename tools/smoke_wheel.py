"""Smoke-test a built wheel: install it into a clean virtualenv and run it for real.

    uv build
    python tools/smoke_wheel.py "dist/*.whl"

Proves the package really ships its UI files, that the `agents-dialpad` command works, and that auth holds.
Uses only the standard library, so it runs the same on Windows, macOS and Linux (CI runs it on all three).
"""
import glob
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url, token=None):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    wheels = sorted(glob.glob(sys.argv[1] if len(sys.argv) > 1 else "dist/*.whl"))
    if not wheels:
        raise SystemExit("no wheel found; run `uv build` first")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        env_dir = tmp / "venv"
        venv.create(env_dir, with_pip=True)
        bindir = env_dir / ("Scripts" if os.name == "nt" else "bin")
        py = bindir / ("python.exe" if os.name == "nt" else "python")
        exe = bindir / ("agents-dialpad.exe" if os.name == "nt" else "agents-dialpad")
        subprocess.run([str(py), "-m", "pip", "install", "--quiet", wheels[-1]], check=True)

        version = subprocess.run([str(exe), "--version"], capture_output=True, text=True, check=True).stdout.strip()
        check(version.startswith("agents-dialpad "), f"command works: {version}")

        data = tmp / "data"
        subprocess.run([str(exe), "--data-dir", str(data), "init", "--yes"], check=True, capture_output=True)
        token = (data / "token.txt").read_text().strip()
        check(len(token) >= 32 and (data / "config.json").exists(), "init created config and token")

        port = free_port()
        log = open(tmp / "serve.log", "w")
        server = subprocess.Popen([str(exe), "--data-dir", str(data), "serve", "--port", str(port)], stdout=log, stderr=subprocess.STDOUT)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(60):
                time.sleep(0.5)
                try:
                    if get(base + "/")[0] == 200:
                        break
                except OSError:
                    pass
            status, html = get(base + "/")
            check(status == 200 and "markdown.js" in html, "UI is served from inside the installed package")
            check(get(base + "/markdown.js")[0] == 200 and get(base + "/app.js")[0] == 200 and get(base + "/style.css")[0] == 200,
                  "all UI files are present in the wheel")
            check(get(base + "/vendor/pdfjs/pdf.min.mjs")[0] == 200 and get(base + "/vendor/pdfjs/pdf.worker.min.mjs")[0] == 200,
                  "pdf.js vendor files are present in the wheel")
            check(get(base + "/api/info")[0] == 401, "API refuses requests without the token")
            status, body = get(base + "/api/info", token)
            check(status == 200 and "projects" in json.loads(body), "API answers with the token")
        finally:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()
            log.close()
        check(token not in (tmp / "serve.log").read_text(errors="replace") or sys.stdout.isatty(),
              "token is not printed when output is not a terminal")
    print("wheel smoke test passed")


if __name__ == "__main__":
    main()
