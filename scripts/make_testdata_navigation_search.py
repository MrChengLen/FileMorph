"""Deterministic QA fixtures for the navigation and format search round (2026-10-29).

/formats now lists each conversion once, under the formats' first names: a
link such as "JPG to PNG" stands for .jpeg files too. These three files carry
the other spellings, so the manual test can drop them on such a link:

* ``foto.jpeg`` — a JPEG photo with the .jpeg extension ("JPG to PNG")
* ``scan.tif``  — a TIFF with the .tif extension ("TIFF to PDF")
* ``seite.htm`` — a small web page with the .htm extension ("HTML to PDF")

Same seed => byte-identical output on every run. Output directory defaults
to ``docs-internal/testdata/navigation-suche/`` next to this repo checkout
(the folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_navigation_search.py [output_dir]
"""

from __future__ import annotations

import io
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SEED = 20261029

_PAGE = """<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><title>Testseite</title></head>
<body>
<h1>Testseite für FileMorph</h1>
<p>Diese Seite hat die Endung .htm und soll als PDF herauskommen.</p>
</body>
</html>
"""


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
            / "navigation-suche"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    buf = io.BytesIO()
    _picture(800, 600, SEED).save(buf, "JPEG", quality=85)
    (out / "foto.jpeg").write_bytes(buf.getvalue())

    buf = io.BytesIO()
    _picture(600, 800, SEED + 1).save(buf, "TIFF", compression="tiff_lzw")
    (out / "scan.tif").write_bytes(buf.getvalue())

    (out / "seite.htm").write_bytes(_PAGE.encode("utf-8"))

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:12} {f.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
