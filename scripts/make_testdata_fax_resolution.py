# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for keeping a fax's resolution (2026-11-09).

A fax in normal mode is scanned at 204 dpi across and 98 down: every pixel is
twice as tall as wide. Each page here carries a circle two inches across and
a line of text, drawn so they look right only at the page's own resolution:
a round circle on an upright page means the resolution was kept, an oval on
a page lying on its side means it was not.

* ``fax-normal.tif`` — one fax page in normal mode (1728 × 1078 dots,
  204 × 98 dpi, Group 4): as PDF an upright letter page with a round circle;
  compressed or as PNG/JPG it still says 204 × 98 dpi
* ``fax-gemischt-3-seiten.tif`` — a fax of three pages: normal, fine
  (204 × 196 dpi, twice the lines) and normal again: as PDF three upright
  pages of the same size, every circle round
* ``bericht-a4.pdf`` — one A4 page to insert the fax into
* ``scan-300dpi.jpg`` — a scanned page as JPG at 300 dpi: compressed it still
  says 300 dpi

Same seed => byte-identical output on every run. Output directory defaults
to ``docs-internal/testdata/fax-aufloesung/`` next to this repo checkout (the
folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_fax_resolution.py [output_dir]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SEED = 20261109
WIDTH = 1728  # dots across a fax line: 8.47 inches at 204 dpi


def _fax_page(label: str, lines_per_inch: int, seed: int) -> Image.Image:
    """A letter page drawn with square dots (204 × 204 dpi), then cut to
    ``lines_per_inch`` lines down as the fax machine scans it."""
    rnd = random.Random(seed)
    words = "der die das und zu den mit von auf ist im nicht ein eine sich als auch".split()
    page = Image.new("L", (WIDTH, 11 * 204), 255)  # 11 inches down
    draw = ImageDraw.Draw(page)
    draw.text((170, 170), label, fill=0, font=ImageFont.load_default(size=90))
    draw.ellipse((660, 500, 660 + 408, 500 + 408), outline=0, width=12)  # 2 inches across
    font = ImageFont.load_default(size=40)
    for top in range(1100, 2100, 70):
        draw.text((170, top), " ".join(rnd.choice(words) for _ in range(12)), fill=0, font=font)
    page = page.resize((WIDTH, 11 * lines_per_inch), Image.Resampling.BOX)
    return page.point(lambda v: 255 if v > 160 else 0).convert("1", dither=Image.Dither.NONE)


def _save_fax(path: Path, pages: list[tuple[Image.Image, tuple[int, int]]]) -> None:
    """A Group 4 TIFF, each page with its own resolution."""
    for page, dpi in pages:
        page.encoderinfo = {"dpi": dpi}
    first = pages[0][0]
    rest = [page for page, _ in pages[1:]]
    first.save(path, "TIFF", compression="group4", save_all=True, append_images=rest)


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent / "docs-internal" / "testdata" / "fax-aufloesung"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    normal, fine = (204, 98), (204, 196)
    _save_fax(out / "fax-normal.tif", [(_fax_page("Fax normal", 98, SEED), normal)])
    _save_fax(
        out / "fax-gemischt-3-seiten.tif",
        [
            (_fax_page("Seite 1 von 3 - normal", 98, SEED + 1), normal),
            (_fax_page("Seite 2 von 3 - fein", 196, SEED + 2), fine),
            (_fax_page("Seite 3 von 3 - normal", 98, SEED + 3), normal),
        ],
    )

    report = Image.new("L", (595, 842), 255)  # A4 in points, saved at 72 dpi
    ImageDraw.Draw(report).text(
        (60, 60), "Bericht - Seite 1", fill=0, font=ImageFont.load_default(size=28)
    )
    # No creation and change dates: the file stays the same on every run.
    report.save(out / "bericht-a4.pdf", "PDF", resolution=72.0, creationDate=None, modDate=None)

    # A letter page at 300 dpi: 8.5 × 11 inches.
    scan = _fax_page("Scan 300 dpi", 204, SEED + 4).convert("L").resize((2550, 3300))
    scan.save(out / "scan-300dpi.jpg", "JPEG", quality=90, dpi=(300, 300))

    for path in sorted(out.iterdir()):
        if path.suffix != ".md":
            print(f"{path.name:28s} {path.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
