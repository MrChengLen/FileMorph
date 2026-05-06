# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.1.c: PDF/A-2b CI fixture generator.

Driver for ``.github/workflows/verapdf.yml``. Builds a small reportlab
PDF that mirrors the worst-case input shape we promise to handle —
unembedded standard-14 Helvetica reference, plain text content, no
images — runs it through :class:`PdfToPdfaConverter`, and writes the
output to ``build/verapdf-fixture.pdf``.

A subsequent CI step runs the official veraPDF Docker image against
that file and fails the workflow on any conformance violation. Both
halves live in the same job so a regression in either the gs-prefix
file or the pikepdf markup pass surfaces as a red CI run rather than
as an issue an end-user discovers in production.

The script is intentionally side-effect-free outside ``build/``:
running it locally on a Linux box with gs + pikepdf installed is the
exact reproducer of what CI does.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repo importable when run from anywhere — matches the
# convention in scripts/bench_conversions.py. CI invokes this as
# ``python scripts/verapdf_check.py`` from the repo root, which puts
# ``scripts/`` (not the repo root) on ``sys.path[0]`` and breaks
# ``from app.…`` imports. Inserting the repo root explicitly fixes
# both the CI invocation and any local ad-hoc run.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from reportlab.pdfgen import canvas  # noqa: E402

from app.converters.pdfa import PdfToPdfaConverter  # noqa: E402


def main() -> int:
    build = Path("build")
    build.mkdir(exist_ok=True)

    source = build / "verapdf-source.pdf"
    c = canvas.Canvas(str(source))
    # Helvetica is one of PDF's standard 14. Without the gs re-render
    # path it would come through unembedded — the exact failure mode
    # we want veraPDF to catch if it ever regresses.
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "FileMorph veraPDF CI fixture")
    c.drawString(72, 700, "Standard-14 reference; gs re-render must subset-embed it.")
    c.showPage()
    c.save()

    output = build / "verapdf-fixture.pdf"
    PdfToPdfaConverter().convert(source, output)
    print(f"PDF/A fixture written to {output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
