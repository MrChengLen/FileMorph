# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the compress follow-ups (2026-11-06).

The manual test compresses or converts each file on the Compress or Convert
page and reads the note, the result card and the download:

* ``messenger-foto.jpg`` — a 2000 × 1500 photo saved at quality 50, as a
  messenger sends it, with camera data and a GPS position (Hamburg) in its
  EXIF block: compressing at quality 85 gives back the original without its
  metadata ("Dein Original, ohne Metadaten")
* ``messenger-foto-gedreht.jpg`` — the same, marked "turned" (orientation 6):
  the original comes back upright, still without camera and GPS data
* ``web-bild.webp`` — a WebP at quality 60 with the same EXIF block
* ``kamera-foto.jpg`` — the photo at quality 98: compressing makes it smaller,
  as before
* ``brief-3-seiten.tif`` — a scanned letter of three pages in black and
  white (Group 4), each page numbered: compressing keeps every page, and as
  PDF it has three pages
* ``fotomappe-3-seiten.tif`` — three colour pictures in one TIFF (LZW),
  numbered: as PNG only the first, with a note to choose PDF
* ``einzelseite.tif`` — one colour page: as PNG without a note
* ``brief-12-seiten.tif`` — a letter of twelve A4 pages at 300 dpi in black
  and white (104 megapixels together — at a byte a pixel, within the limit):
  compressing keeps all twelve
* ``zu-gross-12-seiten-farbe.tif`` — twelve A4 pages at 300 dpi in colour
  (four bytes a pixel: above the limit): refused with a note to split it

Same seed => byte-identical output on every run. Output directory defaults
to ``docs-internal/testdata/komprimieren-folgen/`` next to this repo checkout
(the folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_compress_followups.py [output_dir]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SEED = 20261106


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


def _exif(orientation: int | None = None) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Testkamera"  # Make
    exif[0x0110] = "FM-1"  # Model
    exif[0x0132] = "2026:11:06 10:00:00"  # DateTime
    # GPS: 53° 33' N, 9° 59' E — Hamburg
    exif[0x8825] = {1: "N", 2: (53.0, 33.0, 0.0), 3: "E", 4: (9.0, 59.0, 0.0)}
    if orientation:
        exif[0x0112] = orientation
    return exif.tobytes()


def _numbered(page: Image.Image, text: str, fill) -> Image.Image:
    draw = ImageDraw.Draw(page)
    font = ImageFont.load_default(size=page.height // 12)
    draw.text((page.width // 10, page.height // 10), text, fill=fill, font=font)
    return page


def _letter(number: int, count: int, size: tuple[int, int], seed: int) -> Image.Image:
    """A scanned letter's page in black and white: lines of words, numbered."""
    words = "der die das und zu den mit von auf ist im nicht ein eine sich als auch".split()
    rnd = random.Random(seed)
    page = Image.new("L", size, 255)
    draw = ImageDraw.Draw(page)
    line_font = ImageFont.load_default(size=size[1] // 70)
    for top in range(size[1] // 4, size[1] - size[1] // 10, size[1] // 50):
        line = " ".join(rnd.choice(words) for _ in range(14))
        draw.text((size[0] // 10, top), line, fill=0, font=line_font)
    _numbered(page, f"Seite {number} von {count}", 0)
    return page.point(lambda v: 255 if v > 128 else 0).convert("1", dither=Image.Dither.NONE)


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "komprimieren-folgen"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    photo = _photo(2000, 1500, SEED)
    photo.save(out / "messenger-foto.jpg", "JPEG", quality=50, exif=_exif())
    photo.save(out / "messenger-foto-gedreht.jpg", "JPEG", quality=50, exif=_exif(6))
    photo.resize((1600, 1200)).save(out / "web-bild.webp", "WEBP", quality=60, exif=_exif())
    photo.save(out / "kamera-foto.jpg", "JPEG", quality=98, exif=_exif())

    a4_200dpi = (1654, 2339)
    letter = [_letter(n, 3, a4_200dpi, SEED + n) for n in (1, 2, 3)]
    letter[0].save(
        out / "brief-3-seiten.tif",
        "TIFF",
        compression="group4",
        save_all=True,
        append_images=letter[1:],
    )

    pictures = [
        _numbered(_photo(1200, 900, SEED + 10 + n), f"Bild {n} von 3", (255, 255, 255))
        for n in (1, 2, 3)
    ]
    pictures[0].save(
        out / "fotomappe-3-seiten.tif",
        "TIFF",
        compression="tiff_lzw",
        save_all=True,
        append_images=pictures[1:],
    )
    pictures[0].save(out / "einzelseite.tif", "TIFF", compression="tiff_lzw")

    a4_300dpi = (2480, 3508)  # 8.7 megapixels a page
    pages = [_letter(n, 12, a4_300dpi, SEED + 20 + n) for n in range(1, 13)]
    pages[0].save(
        out / "brief-12-seiten.tif",
        "TIFF",
        compression="group4",
        save_all=True,
        append_images=pages[1:],
    )
    # Plain colour pages: a small file, but four bytes a pixel once decoded.
    colours = [
        _numbered(Image.new("RGB", a4_300dpi, (40 + 15 * n, 90, 160)), f"Seite {n} von 12", "white")
        for n in range(1, 13)
    ]
    colours[0].save(
        out / "zu-gross-12-seiten-farbe.tif",
        "TIFF",
        compression="tiff_adobe_deflate",
        save_all=True,
        append_images=colours[1:],
    )

    for path in sorted(out.iterdir()):
        if path.suffix != ".md":
            print(f"{path.name:32s} {path.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
