# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.1.b: ghostscript-based PDF/A-2b re-render.

Wraps a subprocess call to ghostscript's ``pdfwrite`` device with the
PDF/A-2 conformance flags. Re-rendering is what closes the gap left
by the markup-only path in :mod:`app.converters.pdfa`: a source PDF
with unembedded fonts gets all its glyphs subset-embedded by gs,
which is what veraPDF (NEU-C.1.c) needs to validate at level 2b.

Why a separate module
---------------------
The pdfa.py markup path has zero external runtime dependencies — it
works on every platform pikepdf supports. The ghostscript path is
*optional*: if ``gs`` is not on PATH (Windows local-dev, slim
container images, air-gapped builds), the converter must fall back
to markup-only without crashing. Keeping the gs-specific code in
its own module lets the orchestrator in pdfa.py make a clean
availability check at call time and keeps subprocess plumbing out
of the converter itself.

Why a generated PDFA_def.ps file
--------------------------------
``-dPDFA=2`` alone tells gs to emit the PDF/A-2 markers, but the
spec requires an OutputIntent dictionary with an embedded ICC
profile and gs has no built-in default. The standard pattern is to
feed gs a small PostScript prefix file that registers an ICC stream
and references it from ``/OutputIntents`` on the catalog. We
generate this file at runtime so the ICC bytes (sRGB IEC61966-2.1)
are bundled with the output without depending on the host's gs lib
directory layout — different distros put srgb.icc in different
places.

Conformance scope
-----------------
This slice produces a PDF that veraPDF accepts at level 2b on the
common case (modern editors, embedded or standard fonts). It does
*not* attempt repairs on broken inputs (encrypted, tagged-PDF
violations, unembeddable Type 3 fonts). For those, the markup-only
fallback still produces a structurally valid file that will fail
veraPDF — a clear signal to the operator that the source needs
manual remediation.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_binary() -> str | None:
    """Locate the ghostscript executable on PATH.

    On Linux/macOS the binary is ``gs``; on Windows installs it is
    ``gswin64c`` (console variant of gswin64) and rarely ``gswin32c``.
    We prefer the 64-bit Windows binary because the 32-bit one chokes
    on PDFs above ~2 GiB. Returns None if none is found — callers
    must check :func:`is_available` before invoking the converter."""
    return shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")


# Resolved at import time so callers can short-circuit without paying
# the shutil.which cost on every conversion. None means gs not on PATH.
_GS_BINARY: str | None = _resolve_binary()


class GhostscriptError(RuntimeError):
    """Raised when ghostscript invocation fails or is unavailable."""


def is_available() -> bool:
    """True if a ghostscript binary was found on PATH at import time."""
    return _GS_BINARY is not None


# PostScript prefix that registers the embedded sRGB ICC stream as the
# document's OutputIntent. The {icc_path} placeholder is filled in at
# runtime; PostScript needs forward slashes even on Windows.
#
# The double-braces around {{icc_PDFA}}, {{OutputIntent_PDFA}} and
# {{Catalog}} are how we escape PostScript's literal ``{}`` from
# Python's ``str.format`` — the actual file gets single braces back.
_PDFA_DEF_TEMPLATE = """%!
[ /Title (FileMorph PDF/A Output) /DOCINFO pdfmark
[/_objdef {{icc_PDFA}} /type /stream /OBJ pdfmark
[{{icc_PDFA}} <</N 3>> /PUT pdfmark
[{{icc_PDFA}} ({icc_path}) (r) file /PUT pdfmark
[/_objdef {{OutputIntent_PDFA}} /type /dict /OBJ pdfmark
[{{OutputIntent_PDFA}} <<
  /Type /OutputIntent
  /S /GTS_PDFA1
  /OutputConditionIdentifier (sRGB IEC61966-2.1)
  /Info (sRGB IEC61966-2.1)
  /DestOutputProfile {{icc_PDFA}}
>> /PUT pdfmark
[{{Catalog}} <</OutputIntents [ {{OutputIntent_PDFA}} ]>> /PUT pdfmark
"""


def rerender_to_pdfa(
    input_path: Path,
    output_path: Path,
    *,
    icc_bytes: bytes,
    timeout: int = 60,
) -> Path:
    """Run ghostscript with the PDF/A-2 device, embedding fonts.

    Writes the sRGB ICC profile and a generated PDFA_def.ps to a
    temporary directory, then invokes gs with ``-dPDFA=2``. The
    PostScript prefix wires the ICC stream into ``/OutputIntents``,
    so the resulting PDF passes the §6.2.2 OutputIntent requirement
    in a single pass.

    Raises :class:`GhostscriptError` on any failure mode (binary not
    on PATH, non-zero exit, timeout). The orchestrator in pdfa.py
    catches that exception and falls back to the markup-only path —
    the gs path is opportunistic, never load-bearing."""
    if _GS_BINARY is None:
        raise GhostscriptError("ghostscript not on PATH")

    with tempfile.TemporaryDirectory(prefix="fm_gs_") as tmpdir:
        tmp = Path(tmpdir)
        icc_path = tmp / "srgb.icc"
        icc_path.write_bytes(icc_bytes)
        pdfa_def = tmp / "PDFA_def.ps"
        pdfa_def.write_text(
            _PDFA_DEF_TEMPLATE.format(
                icc_path=str(icc_path).replace("\\", "/"),
            )
        )

        # ``-dPDFACompatibilityPolicy=1`` tells gs to abort on a feature
        # that PDF/A-2 forbids rather than silently strip it — that
        # makes failures visible (caught here, fallback to markup) instead
        # of producing a "looks PDF/A but isn't" file.
        cmd = [
            _GS_BINARY,
            "-dBATCH",
            "-dNOPAUSE",
            "-dNOOUTERSAVE",
            "-dPDFA=2",
            "-dPDFACompatibilityPolicy=1",
            "-sProcessColorModel=DeviceRGB",
            "-sColorConversionStrategy=RGB",
            "-sDEVICE=pdfwrite",
            f"-sOutputFile={output_path}",
            str(pdfa_def),
            str(input_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GhostscriptError(f"ghostscript timed out after {timeout}s") from exc

        if result.returncode != 0:
            tail = result.stderr.decode("utf-8", errors="replace")[-500:].strip()
            raise GhostscriptError(f"ghostscript exit {result.returncode}: {tail or '<no stderr>'}")

    return output_path
