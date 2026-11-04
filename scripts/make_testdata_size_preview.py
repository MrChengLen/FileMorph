"""Deterministic QA fixtures for the compress size estimate (2026-11-04).

The manual test picks each file in Compress mode and reads the line under the
quality slider (one JPEG: the estimated size; otherwise a note), then
compresses and compares the estimate with the result card:

* ``foto.jpg`` — a 3000 × 2000 photo (6 MP): the estimate, then the real size
* ``foto-gedreht.jpg`` — the same photo marked "turned" in its EXIF data
  (phones do this): the estimate still matches
* ``foto-30-megapixel.jpg`` — 6708 × 4472: too large for an estimate in the
  browser, a note instead
* ``foto-graustufen.jpg`` — greyscale: no estimate, a note
* ``bild.webp`` — WebP: no estimate, a note pointing to "By target size"
* ``screenshot.png`` — PNG: no slider, a note and "Convert to WebP instead"
* ``scan.tif`` — an LZW TIFF: no slider; compressing makes it smaller now

Same seed => byte-identical output on every run. Output directory defaults
to ``docs-internal/testdata/groessen-vorschau/`` next to this repo checkout
(the folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_size_preview.py [output_dir]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SEED = 20261104


def _photo(w: int, h: int, seed: int) -> Image.Image:
    """Shapes on a gradient with fine grain — compresses roughly like a photo."""
    rnd = random.Random(seed)
    img = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for _ in range(40):
        x0, y0 = rnd.randint(0, w), rnd.randint(0, h)
        x1, y1 = x0 + rnd.randint(w // 20, w // 3), y0 + rnd.randint(h // 20, h // 3)
        draw.ellipse([x0, y0, x1, y1], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    img = img.filter(ImageFilter.GaussianBlur(2))
    grain = Image.frombytes("L", (w, h), rnd.randbytes(w * h)).convert("RGB")
    return Image.blend(img, grain, 0.08)


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "groessen-vorschau"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    photo = _photo(3000, 2000, SEED)
    photo.save(out / "foto.jpg", "JPEG", quality=92)
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: turned 90°
    photo.save(out / "foto-gedreht.jpg", "JPEG", quality=92, exif=exif)
    _photo(6708, 4472, SEED + 1).save(out / "foto-30-megapixel.jpg", "JPEG", quality=85)
    photo.convert("L").save(out / "foto-graustufen.jpg", "JPEG", quality=92)
    photo.resize((1500, 1000)).save(out / "bild.webp", "WEBP", quality=90)

    shot = Image.new("RGB", (1280, 800), (245, 245, 247))
    draw = ImageDraw.Draw(shot)
    draw.rectangle([0, 0, 1280, 56], fill=(40, 44, 52))
    for row in range(100, 760, 28):
        draw.rectangle([60, row, 60 + (row * 37) % 900 + 200, row + 12], fill=(90, 96, 110))
    shot.save(out / "screenshot.png", "PNG")

    photo.resize((1500, 1000)).save(out / "scan.tif", "TIFF", compression="tiff_lzw")

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:24} {f.stat().st_size / 1024:9.1f} KB")


if __name__ == "__main__":
    main()
