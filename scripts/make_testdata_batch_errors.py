# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the batch error-message manual test round.

Generates the files the manual checklist refers to:

* ``notizen-windows1252.md``  — Markdown saved as windows-1252 (older Windows
  editors); converting it must show the "not UTF-8 text" hint, not a failure
* ``tabelle-windows1252.csv`` — comma-separated CSV in windows-1252, the
  encoding of Excel's classic "CSV" export; same hint, also per file in a batch
* ``daten-kein-array.json``   — valid JSON that is an object, not an array;
  JSON → CSV must say so instead of failing generically
* ``foto.jpg``                — small valid JPEG, the file that succeeds in a
  mixed batch

Same call => byte-identical output on every run. Output directory defaults to
``docs-internal/testdata/batch-errors/`` next to this repo checkout (the
folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_batch_errors.py [output_dir]
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
            Path(__file__).resolve().parent.parent / "docs-internal" / "testdata" / "batch-errors"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    (out / "notizen-windows1252.md").write_bytes(
        "# Einkaufsliste\n\n- Äpfel und Birnen\n- Grüße an Jürgen – 5 €\n".encode("cp1252")
    )
    (out / "tabelle-windows1252.csv").write_bytes(
        "Name,Stadt\r\nMüller,Köln\r\nÖzdemir,Düsseldorf\r\n".encode("cp1252")
    )
    (out / "daten-kein-array.json").write_bytes(
        '{"name": "Müller", "stadt": "Köln"}\n'.encode("utf-8")
    )
    Image.new("RGB", (64, 64), color=(40, 120, 200)).save(out / "foto.jpg", "JPEG", quality=90)

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:26} {f.stat().st_size:8} bytes")


if __name__ == "__main__":
    main()
