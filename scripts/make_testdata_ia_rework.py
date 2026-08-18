"""Deterministic QA fixtures for the IA-rework manual test round (/compress etc.).

Generates three image files with photo-like content (gradients + shapes +
gaussian noise) so the target-size compressor has something real to shrink:

* ``foto-gross.jpg``       — large q95 JPEG, ideal for target-size tests
* ``logo-klein.webp``     — small WebP (also a target-size format)
* ``grafik-mittel.png``   — PNG (deliberately NOT a target-size format:
  the UI must offer quality-only compression for it)

Same seed => byte-identical output on every run. Output directory defaults
to ``docs-internal/testdata/ia-rework/`` next to this repo checkout (the
folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_ia_rework.py [output_dir]
"""

from __future__ import annotations

import io
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SEED = 20260818


def _photo_like(w: int, h: int, seed: int, noise_sigma: int) -> Image.Image:
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
    if noise_sigma:
        noise = Image.effect_noise((w, h), noise_sigma).convert("RGB")
        base = Image.blend(base, noise, 0.18)
    return base


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (Path(__file__).resolve().parent.parent / "docs-internal" / "testdata" / "ia-rework")
    )
    out.mkdir(parents=True, exist_ok=True)

    big = _photo_like(2400, 1600, SEED, noise_sigma=48)
    buf = io.BytesIO()
    big.save(buf, "JPEG", quality=95)
    (out / "foto-gross.jpg").write_bytes(buf.getvalue())

    small = _photo_like(480, 480, SEED + 1, noise_sigma=0)
    buf = io.BytesIO()
    small.save(buf, "WEBP", quality=90)
    (out / "logo-klein.webp").write_bytes(buf.getvalue())

    mid = _photo_like(1200, 900, SEED + 2, noise_sigma=24)
    buf = io.BytesIO()
    mid.save(buf, "PNG")
    (out / "grafik-mittel.png").write_bytes(buf.getvalue())

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:22} {f.stat().st_size / 1_048_576:6.2f} MB")


if __name__ == "__main__":
    main()
