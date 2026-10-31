# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the converter's result preview (2026-10-31).

After "Konvertieren", the result card says how the size changed ("55 % kleiner
als das Original", "Vorher …, jetzt …") and shows a small picture of an image:

* ``foto.jpg`` — an 800 × 600 photo: as WebP it shrinks, as PNG it grows
  several times over (both with a picture); as PDF the card shows the change
  but no picture
* ``logo-transparent.png`` — a black ring and bar on a transparent background:
  the picture must stay visible on the card's grey ground, not vanish into the
  dark page

Same call => byte-identical output on every run. Output directory defaults
to ``docs-internal/testdata/ergebnis-vorschau/`` next to this repo checkout
(the folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_result_preview.py [output_dir]
"""

from __future__ import annotations

import io
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SEED = 20261031


def _photo(w: int, h: int, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for _ in range(40):
        x0, y0 = rnd.randint(0, w), rnd.randint(0, h)
        x1, y1 = x0 + rnd.randint(20, w // 3), y0 + rnd.randint(20, h // 3)
        draw.ellipse([x0, y0, x1, y1], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return img


def _logo(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = min(w, h) // 3
    draw.ellipse([w // 3 - r, h // 2 - r, w // 3 + r, h // 2 + r], outline=(0, 0, 0, 255), width=18)
    draw.rectangle([w // 2 + 20, h // 2 - 22, w - 40, h // 2 + 22], fill=(0, 0, 0, 255))
    return img


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "ergebnis-vorschau"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    buf = io.BytesIO()
    _photo(800, 600, SEED).save(buf, "JPEG", quality=90)
    (out / "foto.jpg").write_bytes(buf.getvalue())

    buf = io.BytesIO()
    _logo(480, 240).save(buf, "PNG")
    (out / "logo-transparent.png").write_bytes(buf.getvalue())

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:22} {f.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
