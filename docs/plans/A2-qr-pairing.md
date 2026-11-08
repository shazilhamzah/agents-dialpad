# A2. QR code pairing and a sidebar "More" menu

- **Size:** S
- **Needs first:** nothing
- **Branch:** `feat/a2-qr-pairing`
- **PR title:** `feat: pair a phone by scanning a QR code`

## Goal

1. `agents-dialpad pair` prints a QR code in the terminal. Scanning it with a phone camera opens agents-dialpad on the
   phone, already signed in.
2. In the web app, a new sidebar **More** menu has **Pair a device**, which shows the same QR code (for adding a second
   phone, or a tablet, from a computer browser).
3. The menu code is generalised so any button can open a menu. Later tasks (B1, B5, C3) add items to this sidebar menu.

## Why

Today the user copies a long URL with a token into the phone by hand. A QR code is the normal way to pair a device.

## Out of scope

Per-device tokens (that is B5). For now the QR contains the existing access token.

## Read first

- `agents_dialpad/cli.py` (how subcommands are added; `COMMANDS`; `local_url`)
- `agents_dialpad/doctor.py` (`tailscale_checks`: how we already call Tailscale)
- `agents_dialpad/app.py`
- `agents_dialpad/static/app.js`: `ICON`, `mountShell()`, `openMenu()`, `closeMenu()`, `onOutside()`, `openSheet()`

## Verify first

1. `tailscale serve status --json` prints an object shaped like this (this was observed on a real machine; host and
   port vary):
   ```json
   { "TCP": { ... }, "Web": { "<host>.<tailnet>.ts.net:8443": { "Handlers": { "/": { "Proxy": "http://127.0.0.1:8787" } } } } }
   ```
   If the shape differs on your machine, stop and report it.
2. `uv add segno` works and `python -c "import segno; q=segno.make('x'); print(hasattr(q,'svg_data_uri'), hasattr(q,'terminal'))"` prints `True True`.

## Steps

### 1. Dependency

Add `segno` (pure Python, no dependencies) to `[project] dependencies` in `pyproject.toml`; run `uv lock`.

### 2. New module `agents_dialpad/pairing.py`

```python
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
```

### 3. CLI: `agents-dialpad pair`

In `cli.py`:

1. Add `"pair"` to `COMMANDS`.
2. Parser: `pair` with `--url` (override the detected base URL), `--png FILE`, `--no-qr`.
3. `cmd_pair(args)`:
   ```text
   cfg, token = config.load()
   base = args.url or pairing.tailscale_url(cfg["port"]) or local_url(cfg)
   remote = base is not the local URL
   link = pairing.pair_link(base, token)
   print a warning: "Anyone who scans this code can use your agents. Do not share or screenshot it."
   if not remote: print "Phone access is not published, so this link only works on this computer. See docs/remote-access.md."
   unless --no-qr: pairing.qr_terminal(link)
   if --png: pairing.qr_png(link, args.png); print "Saved <path>"
   print link
   return 0
   ```

### 4. API: `GET /api/pair`

Inside `create_app`, on the `api` router:

```python
@api.get("/pair")
def pair():
    base = pairing.tailscale_url(cfg["port"])
    link = pairing.pair_link(base or f"http://127.0.0.1:{cfg['port']}/", token)
    return {"url": link, "remote": base is not None, "qr": pairing.qr_svg_data_uri(link)}
```

### 5. UI: generalise the menu

In `app.js`:

1. Add a module-level `let menuAnchor = null;`
2. `openMenu(anchor, items)`: set `menuAnchor = anchor` after creating the menu.
3. `closeMenu()`: instead of `$('#btn-more')`, use `if (menuAnchor) menuAnchor.setAttribute('aria-expanded', 'false'); menuAnchor = null;`
4. `onOutside(e)`: close unless `e.target.closest('#menu')` or `(menuAnchor && menuAnchor.contains(e.target))`.
5. The existing chat menu (`#btn-more`) must still open and close exactly as before.

### 6. UI: sidebar More menu and the pair sheet

1. Add icons to `ICON`:
   - `qr`: `<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM21 14v.01M14 21h.01M17 21h4v-4"/>`
2. In `mountShell()`, in the sidebar header, add between the Limits button and the New chat button:
   `<button class="icon-btn" id="btn-side-more" type="button" aria-label="More" aria-haspopup="menu" aria-expanded="false">${icon('more')}</button>`
3. Wire it: `$('#btn-side-more').onclick = (e) => { if ($('#menu')) return closeMenu(); openMenu(e.currentTarget, sideMenuItems()); };`
4. `function sideMenuItems() { return [{ icon: 'qr', label: 'Pair a device', run: openPair }]; }`
   (later tasks push more items into this list).
5. `async function openPair()`: fetch `/pair`, then `openSheet(...)` with:
   - `<h2>Pair a device</h2>`
   - `<p class="lede">Scan with your phone's camera. Anyone who scans this code can use your agents, so don't share it.</p>`
   - `<div class="qr"><img src="${esc(data.qr)}" alt="QR code that opens agents-dialpad on another device" width="240" height="240"></div>`
   - if `!data.remote`: `<p class="note">Phone access isn't published yet, so this code only works on this computer. Run <code>tailscale serve --bg --https=8443 8787</code> on the computer (see docs/remote-access.md).</p>`
   - actions: **Copy link** (`copyText(data.url)` then `toast('Link copied')`) and **Done**.
6. CSS: `.qr { display: grid; place-items: center; padding: 16px; margin: 12px 0; background: #fff; border-radius: var(--r-m); }`
   The white background is on purpose: QR codes scan most reliably dark-on-white, also in dark mode.

## Tests

`tests/test_pairing.py`:

1. `test_finds_the_https_url_for_our_port`: status with `host.ts.net:8443` → `https://host.ts.net:8443/`.
2. `test_port_443_has_no_port_in_the_url`.
3. `test_other_ports_or_handlers_are_ignored`: proxy to `:9999`, or a handler on `/api` only → `None`.
4. `test_empty_or_malformed_status_returns_none`: `{}`, `{"Web": None}`, `{"Web": {"x:1": None}}`.
5. `test_pair_link_puts_the_token_in_the_fragment`: result contains `/#token=` and no `?`.
6. `test_cli_pair_with_url_prints_the_link(capsys)`: run `cli.main(["--data-dir", ..., "pair", "--url", "https://x.example/", "--no-qr"])`; output contains `https://x.example/#token=`.
7. `test_cli_pair_writes_a_png(tmp_path)`: `--png` file starts with `b"\x89PNG"`.

In `tests/test_integration.py`:

8. `test_pair_endpoint_returns_a_qr_and_needs_the_token`: 401 without token; with token `qr` starts with
   `data:image/svg+xml` and `url` contains `#token=`. Monkeypatch `pairing.tailscale_url` to return `None` so the test
   never calls Tailscale.

## Manual check

1. `uv run agents-dialpad --data-dir <scratch> pair` shows a scannable QR in Windows Terminal, macOS Terminal and a Linux terminal.
2. Scan it with an iPhone camera (Tailscale connected): the app opens, signed in.
3. In the web app: sidebar **More → Pair a device** shows the code; **Copy link** works; the sheet looks right at 375 px and 1280 px, light and dark.
4. The chat "More" menu still opens, closes on outside tap, and closes with Escape.

## Docs

- README: add `agents-dialpad pair` to the commands table; in "Use it from your phone", step 3 becomes "run `agents-dialpad pair` and scan the code".
- `docs/remote-access.md`: mention `agents-dialpad pair` in the Tailscale section.
- CHANGELOG (Added).

## Acceptance checklist

- [ ] Terminal QR scans on a real phone.
- [ ] Web QR scans on a real phone.
- [ ] Warning about not sharing the code is shown in both places.
- [ ] No token is printed by `serve` (unchanged) and none is logged by `/api/pair`.
- [ ] Both menus work (sidebar and chat), including keyboard (arrows, Escape).

## Pitfalls

- Set the `<img>` `src` to the data URI; do not inject the SVG markup with `innerHTML`.
- `segno` terminal output needs UTF-8; the `reconfigure` call above handles Windows consoles.
