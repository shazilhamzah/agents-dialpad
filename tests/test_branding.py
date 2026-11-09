"""The logo: generated icons are valid, match their source, and the app really ships and caches the assets."""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "agents_dialpad" / "static"
sys.path.insert(0, str(ROOT / "tools"))
import make_icons  # noqa: E402


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_icons_are_square_pngs_of_the_declared_size():
    for size in (180, 192, 512):
        assert _png_size((STATIC / f"icon-{size}.png").read_bytes()) == (size, size)


def test_committed_icons_match_the_generator():
    """If this fails someone edited logo-mark.svg or make_icons.py without running `python tools/make_icons.py`."""
    polys = make_icons.flatten(make_icons.load_path())
    assert (STATIC / "icon-192.png").read_bytes() == make_icons.png(192, 0.86, polys)
    assert (STATIC / "favicon.ico").read_bytes() == make_icons.ico((16, 32, 48))
    assert (ROOT / "scripts" / "agents-dialpad.ico").read_bytes() == make_icons.ico((16, 32, 48, 64, 128, 256))


def test_mark_is_drawn_in_the_app_palette_with_the_prompt_cut_out():
    polys = make_icons.flatten(make_icons.load_path())
    size = 128
    cov = make_icons.coverage(polys, size, 0.86)
    assert cov[size // 2][size // 2 + 20] > 0.99       # solid stem/bowl
    assert cov[2][2] == 0                              # background corner
    # the ">" counter is negative space: inside the bowl but not filled
    assert min(cov[row][col] for row in range(size) for col in range(size)) == 0
    png = make_icons.png(64, 0.86, polys)
    assert (make_icons.BG, make_icons.FG) == ((0x09, 0x09, 0x0B), (0x7A, 0xA7, 0xFF))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_ico_files_are_well_formed():
    for path, sizes in ((STATIC / "favicon.ico", [16, 32, 48]), (ROOT / "scripts" / "agents-dialpad.ico", [16, 32, 48, 64, 128, 256])):
        data = path.read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        assert (reserved, kind, count) == (0, 1, len(sizes))
        for i, want in enumerate(sizes):
            w, h, _, _, _, _, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            assert (w or 256, h or 256) == (want, want)
            assert _png_size(data[offset:offset + length]) == (want, want)


def test_svg_logos_use_only_the_app_palette():
    for name in ("logo-mark.svg", "logo-lockup.svg"):
        svg = (STATIC / name).read_text(encoding="utf-8")
        assert set(re.findall(r"#[0-9a-fA-F]{6}", svg)) == {"#7aa7ff", "#1a56e8"}
        assert "<script" not in svg and "href" not in svg
    for name, colour in (("logo-lockup-dark.svg", "#7aa7ff"), ("logo-lockup-light.svg", "#1a56e8")):
        svg = (ROOT / "docs" / "assets" / name).read_text(encoding="utf-8")
        assert set(re.findall(r"#[0-9a-fA-F]{6}", svg)) == {colour}


def test_index_uses_the_logo_and_the_service_worker_caches_it():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'href="/logo-mark.svg"' in index and 'href="/favicon.ico"' in index and 'class="boot"' in index
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"const SHELL = \[(.*?)\];", sw).group(1)
    for url in re.findall(r"'(/[^']*)'", shell):
        if url != "/":
            assert (STATIC / url.lstrip("/")).is_file(), f"service worker caches {url} but it does not exist"
    for url in ("/logo-mark.svg", "/logo-lockup.svg", "/favicon.ico", "/icon-192.png"):
        assert f"'{url}'" in shell
    assert "agents-dialpad-shell-v3'" not in sw        # cache was bumped so installed apps fetch the new logo


def test_assets_are_served(tmp_path):
    from fastapi.testclient import TestClient
    from agents_dialpad import config
    from agents_dialpad.app import create_app

    config.DATA = tmp_path
    client = TestClient(create_app({"port": 8787, "host": "127.0.0.1", "projects": {}, "push_contact": "mailto:a@b.c", "_data_dir": str(tmp_path), "_token_source": "t"}, "tok"))
    for url, kind in (("/logo-mark.svg", "image/svg+xml"), ("/logo-lockup.svg", "image/svg+xml"), ("/favicon.ico", "image"), ("/icon-512.png", "image/png")):
        r = client.get(url)
        assert r.status_code == 200 and r.headers["content-type"].startswith(kind), (url, r.status_code, r.headers.get("content-type"))
