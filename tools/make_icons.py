"""Generate the app icons from the official logo mark, with the standard library only.

    python tools/make_icons.py

The single source of truth is `agents_dialpad/static/logo-mark.svg` (Concept B: a geometric lowercase "d" whose
counter is a negative-space ">" prompt). Its path is flattened and filled here, so no SVG library is needed.

Writes:
    agents_dialpad/static/icon-180.png, icon-192.png, icon-512.png, favicon.ico
    scripts/agents-dialpad.ico
"""
import math
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "agents_dialpad" / "static"
MARK_SVG = STATIC / "logo-mark.svg"

BG = (0x09, 0x09, 0x0B)          # #09090b, the app's dark background (and manifest background_color)
FG = (0x7A, 0xA7, 0xFF)          # #7aa7ff, the app's accent on dark
VIEWBOX = 256.0
CENTER = (128.0, 126.0)          # centre of the mark's bounding box in the 256 x 256 viewBox
SUBROWS = 8                      # vertical samples per pixel row (horizontal coverage is exact)


# ---------------------------------------------------------------- SVG path -> polygons
def load_path(svg: Path = MARK_SVG) -> str:
    m = re.search(r'<path[^>]*\sd="([^"]+)"', svg.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"no <path d=...> found in {svg}")
    return m.group(1)


def _arc(x1, y1, rx, ry, large, sweep, x2, y2):
    """Points along an SVG elliptical arc (circular is all the logo needs), per SVG spec F.6.5 with no rotation."""
    if (x1, y1) == (x2, y2):
        return []
    rx, ry = abs(rx), abs(ry)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    lam = (dx / rx) ** 2 + (dy / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
    den = rx * rx * dy * dy + ry * ry * dx * dx
    coef = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cxp, cyp = coef * rx * dy / ry, -coef * ry * dx / rx
    cx, cy = cxp + (x1 + x2) / 2, cyp + (y1 + y2) / 2
    t1 = math.atan2((dy - cyp) / ry, (dx - cxp) / rx)
    t2 = math.atan2((-dy - cyp) / ry, (-dx - cxp) / rx)
    dt = t2 - t1
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    steps = max(4, math.ceil(abs(dt) / (math.pi / 90)))
    return [(cx + rx * math.cos(t1 + dt * i / steps), cy + ry * math.sin(t1 + dt * i / steps)) for i in range(1, steps + 1)]


def flatten(d: str):
    """Absolute M L H V A Z only (what the logo uses). Returns a list of closed polygons in viewBox units."""
    tokens = re.findall(r"[MLHVAZ]|-?\d+(?:\.\d+)?", d)
    polys, cur, i, x, y = [], [], 0, 0.0, 0.0
    n_args = {"M": 2, "L": 2, "H": 1, "V": 1, "A": 7, "Z": 0}
    cmd = None
    while i < len(tokens):
        if tokens[i] in n_args:
            cmd = tokens[i]
            i += 1
            if cmd == "Z":
                if cur:
                    polys.append(cur)
                cur = []
                continue
        elif cmd is None:
            raise SystemExit("path data must start with a command")
        args = [float(t) for t in tokens[i:i + n_args[cmd]]]
        if len(args) != n_args[cmd]:
            raise SystemExit(f"bad arguments for {cmd}")
        i += n_args[cmd]
        if cmd == "M":
            x, y = args
            cur = [(x, y)]
            cmd = "L"                      # extra pairs after M are implicit lineto
        elif cmd == "L":
            x, y = args
            cur.append((x, y))
        elif cmd == "H":
            x = args[0]
            cur.append((x, y))
        elif cmd == "V":
            y = args[0]
            cur.append((x, y))
        elif cmd == "A":
            rx, ry, _rot, large, sweep, ex, ey = args
            cur.extend(_arc(x, y, rx, ry, int(large), int(sweep), ex, ey))
            x, y = ex, ey
    if cur:
        polys.append(cur)
    return polys


# ---------------------------------------------------------------- rasterising
def coverage(polys, size: int, fit: float):
    """Per-pixel coverage 0..1 of the polygons (even-odd) with the mark scaled by `fit` about the tile centre."""
    k = size * fit / VIEWBOX
    ox, oy = size / 2 - CENTER[0] * k, size / 2 - CENTER[1] * k
    edges = []
    for poly in polys:
        pts = [(ox + px * k, oy + py * k) for px, py in poly]
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
            if ay != by:
                edges.append((min(ay, by), max(ay, by), ax, (bx - ax) / (by - ay), ay))
    cov = [[0.0] * size for _ in range(size)]
    for row in range(size):
        acc = cov[row]
        for s in range(SUBROWS):
            yy = row + (s + 0.5) / SUBROWS
            xs = sorted(ax + (yy - ay) * slope for y0, y1, ax, slope, ay in edges if y0 <= yy < y1)
            for a, b in zip(xs[0::2], xs[1::2]):
                a, b = max(a, 0.0), min(b, float(size))
                if b <= a:
                    continue
                ia, ib = int(a), min(int(b), size - 1)
                if ia == ib:
                    acc[ia] += (b - a) / SUBROWS
                else:
                    acc[ia] += (ia + 1 - a) / SUBROWS
                    for px in range(ia + 1, ib):
                        acc[px] += 1 / SUBROWS
                    acc[ib] += (b - ib) / SUBROWS
    return cov


def png(size: int, fit: float = 0.86, polys=None) -> bytes:
    """A square RGB PNG: the mark in FG on BG. fit=0.86 keeps it inside the maskable safe zone (centre 80% circle)."""
    polys = polys if polys is not None else flatten(load_path())
    cov = coverage(polys, size, fit)
    rows = []
    for row in range(size):
        line = bytearray([0])
        for c in cov[row]:
            c = min(1.0, c)
            line += bytes(round(BG[i] + (FG[i] - BG[i]) * c) for i in range(3))
        rows.append(bytes(line))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(sizes=(16, 32, 48, 64, 128, 256), fit: float = 1.15) -> bytes:
    """A Windows .ico holding PNG-compressed images (supported since Windows Vista). Larger mark: it is shown small."""
    polys = flatten(load_path())
    images = [(s, png(s, fit, polys)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return header + entries + blobs


if __name__ == "__main__":
    polys = flatten(load_path())
    for size, fit in ((180, 1.0), (192, 0.86), (512, 0.86)):     # 180 is the iOS home-screen icon (iOS rounds it itself)
        target = STATIC / f"icon-{size}.png"
        target.write_bytes(png(size, fit, polys))
        print("wrote", target)
    for target, sizes in ((STATIC / "favicon.ico", (16, 32, 48)), (ROOT / "scripts" / "agents-dialpad.ico", (16, 32, 48, 64, 128, 256))):
        target.write_bytes(ico(sizes))
        print("wrote", target)
