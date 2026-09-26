# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the batch ZIP name manual test round.

Generates the files the manual checklist refers to:

* ``foto.jpg``, ``foto.webp``, ``foto_1.jpg`` — small red, green and blue
  images. Converted to PNG in one batch, two of them become ``foto.png`` and
  one ``foto_1.png``, so the ZIP must still hold three different names
* ``manifest.csv`` — a small UTF-8 table; converted to JSON it becomes
  ``manifest.json``, the name of the report in a batch with a failed file
* ``kaputt.jpg``   — text with a .jpg name, so its conversion fails and the
  batch carries that report

Same call => byte-identical output on every run. Output directory defaults to
``docs-internal/testdata/batch-zip-names/`` next to this repo checkout (the
folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_batch_zip_names.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "batch-zip-names"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    Image.new("RGB", (64, 64), color=(200, 40, 40)).save(out / "foto.jpg", "JPEG", quality=90)
    Image.new("RGB", (64, 64), color=(40, 160, 60)).save(out / "foto.webp", "WEBP", lossless=True)
    Image.new("RGB", (64, 64), color=(40, 90, 200)).save(out / "foto_1.jpg", "JPEG", quality=90)
    (out / "manifest.csv").write_bytes(b"Stadt,Einwohner\nHamburg,1900000\nBremen,570000\n")
    (out / "kaputt.jpg").write_bytes(b"Das ist kein Bild, nur Text mit .jpg-Endung.\n")

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:14} {f.stat().st_size:6} bytes")


if __name__ == "__main__":
    main()
