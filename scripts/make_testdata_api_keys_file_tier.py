# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the API_KEYS_FILE_TIER manual test round.

Generates the files the manual checklist refers to:

* ``bild-a.jpg``, ``bild-b.jpg`` — two small pictures for a two-file batch,
  which the anonymous tier refuses (1 file per batch) and a lifted key tier
  accepts
* ``foto-gross-35mb.bmp`` — an uncompressed 3500x3500 BMP (35.05 MB), just
  above the anonymous 30 MB file cap and far below Pro's

Same call => byte-identical output on every run (seeded shapes; BMP and JPEG
carry no timestamps). Output directory defaults to
``docs-internal/testdata/api-keys-file-tier/`` next to this repo checkout
(the folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_api_keys_file_tier.py [output_dir]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SEED = 20260928


def _picture(w: int, h: int, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for _ in range(60):
        x0, y0 = rnd.randint(0, w), rnd.randint(0, h)
        x1, y1 = x0 + rnd.randint(20, w // 3), y0 + rnd.randint(20, h // 3)
        color = tuple(rnd.randint(0, 255) for _ in range(3))
        if rnd.random() < 0.5:
            draw.ellipse([x0, y0, x1, y1], fill=color)
        else:
            draw.rectangle([x0, y0, x1, y1], fill=color)
    return img


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "api-keys-file-tier"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    _picture(800, 600, SEED).save(out / "bild-a.jpg", "JPEG", quality=90)
    _picture(800, 600, SEED + 1).save(out / "bild-b.jpg", "JPEG", quality=90)
    # BMP is uncompressed, so the size is 3500 x 3500 x 3 bytes whatever the content.
    _picture(3500, 3500, SEED + 2).save(out / "foto-gross-35mb.bmp", "BMP")

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:22} {f.stat().st_size / 1_048_576:6.2f} MB")


if __name__ == "__main__":
    main()
