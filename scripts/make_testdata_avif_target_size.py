# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the AVIF target-size manual test round.

Generates the files the manual checklist refers to, all with photo-like
content (gradient + shapes + grain) so the target-size search has real work:

* ``foto-4mp.avif``   — 2400x1600 AVIF, the typical case: "By target size"
  is offered, the slow-encode hint appears, a smaller target is reached
* ``foto-12mp.avif``  — 4200x2800 AVIF (phone-photo size), the slow case the
  hint warns about (target 1 MB took ~26 s locally on 2 cores)
* ``foto-4mp.jpg``    — the same picture as JPEG: target size is offered,
  but the AVIF hint must stay hidden

Same call => byte-identical output on every run (seeded noise; single-thread
AVIF encode). Output directory defaults to
``docs-internal/testdata/avif-target-size/`` next to this repo checkout (the
folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_avif_target_size.py [output_dir]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pillow_avif  # noqa: F401  (registers AVIF with Pillow on import)
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SEED = 20260926


def _photo_like(w: int, h: int, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    base = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    tint = (rnd.randint(40, 200), rnd.randint(40, 200), rnd.randint(40, 200))
    base = Image.blend(base, Image.new("RGB", (w, h), tint), 0.45)
    draw = ImageDraw.Draw(base)
    for _ in range(80):
        x0, y0 = rnd.randint(0, w), rnd.randint(0, h)
        x1, y1 = x0 + rnd.randint(40, w // 3), y0 + rnd.randint(40, h // 3)
        color = tuple(rnd.randint(0, 255) for _ in range(3))
        if rnd.random() < 0.5:
            draw.ellipse([x0, y0, x1, y1], fill=color)
        else:
            draw.rectangle([x0, y0, x1, y1], fill=color)
    base = base.filter(ImageFilter.GaussianBlur(3))
    # Seeded grain (Image.effect_noise is not seedable): uniform bytes squeezed
    # to +-16 around 128, then added with offset -128.
    grain = Image.frombytes("L", (w, h), rnd.randbytes(w * h))
    grain = grain.point(lambda v: 128 + (v - 128) // 8).convert("RGB")
    return ImageChops.add(base, grain, scale=1.0, offset=-128)


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "avif-target-size"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    mid = _photo_like(2400, 1600, SEED)
    mid.save(out / "foto-4mp.avif", "AVIF", quality=80, speed=8, max_threads=1)
    mid.save(out / "foto-4mp.jpg", "JPEG", quality=92)
    big = _photo_like(4200, 2800, SEED + 1)
    big.save(out / "foto-12mp.avif", "AVIF", quality=80, speed=8, max_threads=1)

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:16} {f.stat().st_size / 1_048_576:6.2f} MB")


if __name__ == "__main__":
    main()
