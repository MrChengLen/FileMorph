# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pillow decompression-bomb hardening — startup-time configuration.

Pillow ships two thresholds on ``Image.MAX_IMAGE_PIXELS``:

- pixel-count above the threshold → ``DecompressionBombWarning`` (the
  default behaviour is *warn but continue decoding*),
- pixel-count above 2× the threshold → ``DecompressionBombError``
  raised synchronously, decode aborted.

A warning that doesn't halt the worker is a denial-of-service vector for
a file-conversion service: a 200 kB PNG whose IHDR claims 60 000 × 60 000
pixels (~3.6 gigapixels) coasts past every input-size check but pins the
worker for tens of seconds decoding into ~14 GB of RGBA memory. The
output-cap guard (``app/core/quotas.py``) would catch the result *after*
the decode, by which point the host has already paid the cost.

This module flips the warning to a hard error at import time so every
``Image.open(...)`` call site in the codebase fails fast and identically.
The chosen threshold matches Pillow's default (~89 megapixels —
``178 956 970`` would be the 2× ceiling). Tier-aware overrides go via the
``FILEMORPH_IMAGE_MAX_MEGAPIXELS`` env var; self-hosters with
explicit large-image use cases (high-res scans, GIS, microscopy)
bump it.

The resulting ``DecompressionBombError`` is a ``ValueError`` subclass; the
route handlers in ``app/api/routes/convert.py`` and ``compress.py`` catch
it specifically and emit HTTP 400 with
``X-FileMorph-Error-Code: decompression_bomb`` so the UI can render a
distinct error rather than the generic "Conversion failed" message.

Threat model reference: PT-008 territory of
``docs/security-pentest-report.md`` (the static-review item that flagged
the warn-but-continue default). The companion guard for output-size is
in ``app/core/quotas.py`` (per-tier output cap) — that one rejects *after*
encoding; this one rejects *before* decoding.

Import order matters: ``import app.core.image_hardening`` must run *before*
the first ``Image.open(...)`` call in the application path. The current
chain is ``app/main.py → from app.api.routes import …`` which imports the
converter modules; importing this from ``app/main.py`` at module top puts
the warning filter in place before any route module runs.
"""

from __future__ import annotations

import os
import warnings

from PIL import Image

# Default matches Pillow's stock threshold so existing legitimate uploads
# keep working unchanged. The 2× ceiling lives below at
# ``DecompressionBombError``-raising time (Pillow internal); we tighten
# the *warning* threshold to also raise.
_DEFAULT_MAX_MEGAPIXELS = 89


def _resolve_max_pixels() -> int:
    """Return the configured MAX_IMAGE_PIXELS, honouring env override.

    Env override is documented in ``.env.example`` and
    ``docs/self-hosting.md``. Garbage values fall back to the Pillow-
    compatible default rather than refusing to boot — a self-hoster
    misconfiguring this should still get a working service.
    """
    raw = os.environ.get("FILEMORPH_IMAGE_MAX_MEGAPIXELS", "").strip()
    if not raw:
        return _DEFAULT_MAX_MEGAPIXELS * 1_000_000
    try:
        mp = int(raw)
        if mp < 1 or mp > 10_000:
            raise ValueError
        return mp * 1_000_000
    except ValueError:
        return _DEFAULT_MAX_MEGAPIXELS * 1_000_000


def apply_hardening() -> None:
    """Set MAX_IMAGE_PIXELS + filter DecompressionBombWarning to an error.

    Idempotent — safe to call multiple times. Re-reads the env var so a
    test can monkeypatch the env between calls and reapply.
    """
    Image.MAX_IMAGE_PIXELS = _resolve_max_pixels()
    # Promote the warning to a synchronously raised error. Pillow's own
    # DecompressionBombError class still fires above the 2× ceiling; this
    # filter closes the warn-but-continue gap below it so EVERY oversize
    # image fails fast and identically.
    warnings.simplefilter("error", Image.DecompressionBombWarning)


# Fire once at import so a single ``import app.core.image_hardening``
# anywhere in the startup path is enough. ``app/main.py`` does this
# explicitly to make the dependency obvious.
apply_hardening()
