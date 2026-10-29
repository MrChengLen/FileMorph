"""Deterministic QA fixture for link previews, icons and accessibility (2026-10-29).

The manual test converts one photo on a phone — once from the home-screen icon
(the page opens without the browser bar) and once with the screen reader on, to
hear "processing" and the result being read out:

* ``testfoto.jpg`` — an 800 × 600 JPEG photo (a few hundred KB at most)

Same seed => byte-identical output on every run. Output directory defaults
to ``docs-internal/testdata/vorschau-barrierefreiheit/`` next to this repo
checkout (the folder is gitignored — commit this script, never the data) and
can be overridden as the first CLI argument.

Run:
    python scripts/make_testdata_a11y_preview.py [output_dir]
"""

from __future__ import annotations

import io
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SEED = 20261029


def _picture(w: int, h: int, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for _ in range(24):
        x0, y0 = rnd.randint(0, w), rnd.randint(0, h)
        x1, y1 = x0 + rnd.randint(20, w // 3), y0 + rnd.randint(20, h // 3)
        draw.ellipse([x0, y0, x1, y1], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return img


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "vorschau-barrierefreiheit"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    buf = io.BytesIO()
    _picture(800, 600, SEED).save(buf, "JPEG", quality=85)
    (out / "testfoto.jpg").write_bytes(buf.getvalue())

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:12} {f.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
