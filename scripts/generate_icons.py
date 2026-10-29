#!/usr/bin/env python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate the raster icons from the logo in ``app/static/favicon.svg``.

- ``apple-touch-icon.png`` (180x180) — iOS home screen; opaque, square
  (iOS rounds the corners itself and paints transparent pixels black).
- ``icon-192.png`` / ``icon-512.png`` — Android home screen via
  ``site.webmanifest``; the 512 one doubles as the maskable icon (the mark
  stays inside the 40 % safe circle).
- ``favicon.ico`` (16/32/48) — transparent like the SVG, for clients without
  SVG favicons.

Pillow-only, like ``scripts/generate_og_image.py``: the SVG is one stroked
path (24-unit viewBox, stroke-width 2, round caps and joins) — a tray of lines
and four r=2 quarter arcs plus an arrow — drawn here at 2048 px and scaled
down with LANCZOS. The path is hard-coded and checked against the SVG, so a
logo change fails loudly instead of drifting. Re-run after a logo change:

    python scripts/generate_icons.py
"""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"

PATH = "M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"
STROKE = (0x63, 0x66, 0xF1)  # #6366f1, the SVG's stroke
BACKGROUND = (0x0F, 0x11, 0x17)  # #0f1117, site.webmanifest background_color
CANVAS = 2048


def _arc(start, end, centre, steps=48):
    """Points on the shorter circular arc from start to end around centre."""
    a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
    a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
    delta = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    r = math.dist(start, centre)
    return [
        (
            centre[0] + r * math.cos(a0 + delta * i / steps),
            centre[1] + r * math.sin(a0 + delta * i / steps),
        )
        for i in range(1, steps + 1)
    ]


_TRAY = [
    (8, 7),
    (5, 7),
    *_arc((5, 7), (3, 9), (5, 9)),
    (3, 18),
    *_arc((3, 18), (5, 20), (5, 18)),
    (19, 20),
    *_arc((19, 20), (21, 18), (19, 18)),
    (21, 9),
    *_arc((21, 9), (19, 7), (19, 9)),
    (16, 7),
]
SUBPATHS = [_TRAY, [(15, 11), (12, 14)], [(12, 14), (9, 11)], [(12, 14), (12, 4)]]


def _render(size: int, opaque: bool, unit: float, offset: float) -> Image.Image:
    """Draw the mark at CANVAS px; unit and offset are in output pixels."""
    k = CANVAS / size
    img = Image.new("RGBA", (CANVAS, CANVAS), (*BACKGROUND, 255) if opaque else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    width = 2 * unit * k
    r = width / 2
    for sub in SUBPATHS:
        pts = [(offset * k + x * unit * k, offset * k + y * unit * k) for x, y in sub]
        # Plain wide segments plus a disc on every vertex give round caps and
        # joins (Pillow's joint="curve" leaves spikes on the short arc segments).
        for a, b in zip(pts, pts[1:]):
            draw.line([a, b], fill=(*STROKE, 255), width=round(width))
        for x, y in pts:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(*STROKE, 255))
    out = img.resize((size, size), Image.LANCZOS)
    return out.convert("RGB") if opaque else out


def _tile(size: int) -> Image.Image:
    """Home-screen tile: opaque background, the mark ~60 % wide (about 20 % margin)."""
    unit = size * 0.03
    return _render(size, True, unit, size / 2 - 12 * unit)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def main() -> None:
    svg = (STATIC / "favicon.svg").read_text(encoding="utf-8")
    if PATH not in svg or 'stroke="#6366f1"' not in svg or 'stroke-width="2"' not in svg:
        raise SystemExit("favicon.svg changed — update PATH/SUBPATHS here first")

    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        (STATIC / name).write_bytes(_png(_tile(size)))

    # favicon.ico: one frame per size, each drawn at its own size.
    ico = {n: _render(n, False, n / 24, 0) for n in (16, 32, 48)}
    ico[48].save(
        STATIC / "favicon.ico",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[ico[16], ico[32]],
    )
    print("wrote apple-touch-icon.png, icon-192.png, icon-512.png, favicon.ico")


if __name__ == "__main__":
    main()
