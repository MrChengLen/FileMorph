#!/usr/bin/env python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate ``app/static/og-image.png`` (1200x630 social-preview card).

Pillow-only (no SVG rasteriser needed) so it runs anywhere. The logo mark is
drawn directly from the **same path geometry as** ``app/static/favicon.svg``
(a document-tray + download arrow), so the social card stays in lock-step with
the live-site logo instead of drifting into a separate mark. Re-run after any
logo/wording change:

    python scripts/generate_og_image.py

Rendered at 3x then downsampled (LANCZOS) for crisp edges/text.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "og-image.png"

W, H = 1200, 630
SS = 3  # supersample factor

BRAND = (99, 102, 241)  # #6366f1 — same indigo as favicon.svg stroke
WORDMARK = (244, 245, 250)  # near-white, matches navbar wordmark on dark bg
TAGLINE = (148, 163, 184)  # slate-400
CHIP = (129, 140, 248)  # indigo-400
BG_TOP = (13, 16, 26)  # subtle lighter top
BG_BOT = (4, 5, 12)  # near bg-gray-950 at the bottom

_BOLD = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
_REG = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_logo(draw: ImageDraw.ImageDraw, ox: float, oy: float, size: float) -> None:
    """Replicate favicon.svg (viewBox 0 0 24 24): a tray (open at top-centre)
    with a download arrow pointing into it. Stroke-only, round caps/joins."""
    s = size / 24.0
    w = max(2, round(2 * s))  # SVG stroke-width=2
    r = w / 2

    def P(x: float, y: float) -> tuple[float, float]:
        return (ox + x * s, oy + y * s)

    def dot(pt: tuple[float, float]) -> None:  # round cap / join
        draw.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=BRAND)

    def seg(a: tuple[float, float], b: tuple[float, float]) -> None:
        draw.line([P(*a), P(*b)], fill=BRAND, width=w)
        dot(P(*a))
        dot(P(*b))

    def corner(cx: float, cy: float, start: int, end: int) -> None:
        x0, y0 = P(cx - 2, cy - 2)
        x1, y1 = P(cx + 2, cy + 2)
        draw.arc([x0, y0, x1, y1], start, end, fill=BRAND, width=w)

    # Tray straight edges (top is open between x=8 and x=16 for the arrow)
    seg((5, 7), (8, 7))  # top-left stub
    seg((16, 7), (19, 7))  # top-right stub
    seg((3, 9), (3, 18))  # left
    seg((5, 20), (19, 20))  # bottom
    seg((21, 9), (21, 18))  # right
    # Rounded corners (radius 2)
    corner(5, 9, 180, 270)  # top-left
    corner(5, 18, 90, 180)  # bottom-left
    corner(19, 18, 0, 90)  # bottom-right
    corner(19, 9, 270, 360)  # top-right
    # Download arrow: stem + downward chevron, pointing into the tray
    seg((12, 4), (12, 14))
    seg((9, 11), (12, 14))
    seg((15, 11), (12, 14))


def build() -> None:
    cw, ch = W * SS, H * SS
    img = Image.new("RGB", (cw, ch), BG_BOT)
    draw = ImageDraw.Draw(img)

    # Vertical gradient background
    for y in range(ch):
        t = y / ch
        col = tuple(round(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (cw, y)], fill=col)

    # Logo (left), vertically centred
    logo_size = 150 * SS
    ox = 96 * SS
    oy = (ch - logo_size) / 2
    _draw_logo(draw, ox, oy, logo_size)

    # Text block (right of the logo)
    tx = 290 * SS
    wordmark = _font(_BOLD, 96 * SS)
    tagline = _font(_REG, 34 * SS)
    chips = _font(_REG, 30 * SS)

    draw.text((tx, 214 * SS), "FileMorph", font=wordmark, fill=WORDMARK, anchor="la")
    draw.text(
        (tx, 330 * SS),
        "Privacy-first file converter & compressor",
        font=tagline,
        fill=TAGLINE,
        anchor="la",
    )
    draw.text(
        (tx, 392 * SS),
        "EU-hosted   ·   AGPLv3   ·   self-hostable",
        font=chips,
        fill=CHIP,
        anchor="la",
    )

    img = img.resize((W, H), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"wrote {OUT} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    build()
