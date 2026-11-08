"""Generate the PWA icons (a ">_" prompt glyph) with the standard library only.

    python tools/make_icons.py
"""
import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static"
BG = (15, 20, 32)
FG = (122, 162, 255)

# glyph segments in unit coordinates (kept inside the maskable safe zone)
SEGS = [((0.32, 0.31), (0.56, 0.50)), ((0.56, 0.50), (0.32, 0.69)), ((0.61, 0.69), (0.78, 0.69))]
HALF = 0.05


def dist(px, py, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def png(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            d = min(dist((x + 0.5) / size, (y + 0.5) / size, a, b) for a, b in SEGS)
            k = max(0.0, min(1.0, (HALF - d) * size + 0.5))  # 1px antialias
            row += bytes(round(BG[i] + (FG[i] - BG[i]) * k) for i in range(3))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(sizes=(16, 32, 48, 64, 128, 256)) -> bytes:
    """A Windows .ico holding PNG-compressed images (supported since Windows Vista)."""
    images = [(s, png(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return header + entries + blobs


if __name__ == "__main__":
    for s in (180, 192, 512):
        (OUT / f"icon-{s}.png").write_bytes(png(s))
        print("wrote", OUT / f"icon-{s}.png")
    target = Path(__file__).resolve().parent.parent / "scripts" / "agents-dialpad.ico"
    target.write_bytes(ico())
    print("wrote", target)
