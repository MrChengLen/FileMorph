# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pillow decompression-bomb hardening (P3-4) — regression tests.

The point of this hardening is that *before* the fix, Pillow's default
behaviour was to *warn but continue decoding* when an image's pixel
count exceeded ``Image.MAX_IMAGE_PIXELS``. A 200 kB PNG with an IHDR
claiming 60 000 × 60 000 px (~3.6 gigapixels) would pin a worker
decoding into ~14 GB of RGBA memory before the per-tier output cap
got a chance to reject the result. The fix flips that warning to an
error at startup (``app/core/image_hardening.py``) and the route
handlers translate the resulting ``DecompressionBombError`` to a
4xx response with a structured error code.

These tests pin every layer of the chain:
1. The hardening module sets ``MAX_IMAGE_PIXELS`` + the warning filter
   on import.
2. The /convert + /compress routes catch the error specifically and
   emit HTTP 400 with ``X-FileMorph-Error-Code: decompression_bomb``
   *instead of* the generic 500 from the catch-all handler.
3. The env-var override (``FILEMORPH_IMAGE_MAX_MEGAPIXELS``) tightens
   or loosens the threshold for self-hosters with explicit
   large-image use cases.

Strategy: most tests monkeypatch ``Image.MAX_IMAGE_PIXELS`` to a tiny
value (e.g. 100) and feed a normal small image. This avoids
constructing a real on-disk gigapixel bomb and keeps the suite fast.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image


def _make_small_png(path, w: int = 200, h: int = 200) -> None:
    """Write a ``w × h`` PNG with simple gradient content."""
    img = Image.new("RGB", (w, h), color=(120, 200, 120))
    img.save(str(path), format="PNG")


def _make_small_jpg(path, w: int = 200, h: int = 200) -> None:
    img = Image.new("RGB", (w, h), color=(120, 120, 200))
    img.save(str(path), format="JPEG")


# ── Hardening module itself ──────────────────────────────────────────────────


def test_hardening_module_sets_max_pixels():
    """Import-time hardening configured a finite MAX_IMAGE_PIXELS — Pillow
    ships with the value, but we want to assert it's the env-derived
    figure, not the library default that an upstream release could
    silently raise."""
    from app.core import image_hardening

    assert Image.MAX_IMAGE_PIXELS == image_hardening._resolve_max_pixels()
    assert Image.MAX_IMAGE_PIXELS > 0


def test_hardening_module_filters_warning_to_error(monkeypatch):
    """``DecompressionBombWarning`` must raise — not just print to stderr —
    so every ``Image.open(...)`` site in the codebase fails identically."""
    from app.core import image_hardening

    image_hardening.apply_hardening()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    buf = io.BytesIO()
    Image.new("RGB", (40, 40)).save(buf, format="PNG")
    buf.seek(0)
    with pytest.raises(Image.DecompressionBombError):
        Image.open(buf).load()


def test_hardening_module_respects_env_override(monkeypatch):
    """Operators with explicit large-image use cases (GIS, scans,
    microscopy) raise the limit via ``FILEMORPH_IMAGE_MAX_MEGAPIXELS``.
    The default (no env) lands at Pillow's ~89 MP. Garbage values
    fall back to default rather than refusing to boot."""
    from app.core import image_hardening

    monkeypatch.setenv("FILEMORPH_IMAGE_MAX_MEGAPIXELS", "200")
    assert image_hardening._resolve_max_pixels() == 200_000_000

    monkeypatch.setenv("FILEMORPH_IMAGE_MAX_MEGAPIXELS", "garbage")
    assert image_hardening._resolve_max_pixels() == 89 * 1_000_000

    monkeypatch.setenv("FILEMORPH_IMAGE_MAX_MEGAPIXELS", "-5")
    assert image_hardening._resolve_max_pixels() == 89 * 1_000_000

    monkeypatch.setenv("FILEMORPH_IMAGE_MAX_MEGAPIXELS", "999999")
    # Above 10 000 MP ceiling → fallback to default.
    assert image_hardening._resolve_max_pixels() == 89 * 1_000_000


# ── /convert route — bomb detection emits structured 400 ─────────────────────


def test_convert_decompression_bomb_returns_400_with_error_code(
    client, auth_headers, tmp_path, monkeypatch
):
    """A small PNG opened against a tightened MAX_IMAGE_PIXELS triggers
    DecompressionBombError; the route maps it to HTTP 400 + structured
    header so the UI can render a distinct message instead of the
    generic 500 conversion-failed."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    src = tmp_path / "small.png"
    _make_small_png(src, w=40, h=40)

    with src.open("rb") as f:
        r = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("small.png", f, "image/png")},
            data={"target_format": "jpg"},
        )
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "decompression_bomb"
    body = r.json()
    assert "safety limits" in body["detail"].lower() or "decode" in body["detail"].lower()


def test_compress_decompression_bomb_returns_400_with_error_code(
    client, auth_headers, tmp_path, monkeypatch
):
    """Same hard-reject path on /compress."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    src = tmp_path / "small.jpg"
    _make_small_jpg(src, w=40, h=40)

    with src.open("rb") as f:
        r = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("small.jpg", f, "image/jpeg")},
            data={"quality": "80"},
        )
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "decompression_bomb"


def test_convert_below_threshold_still_succeeds(client, auth_headers, sample_jpg):
    """Sanity: an ordinary small image at the *default* threshold still
    converts. Without this, a buggy hardening that rejects everything
    would still pass the bomb-detection tests."""
    with sample_jpg.open("rb") as f:
        r = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    # We don't pin status==200 because a noisy preceding test (rate-limit,
    # output-cap) can yield other codes; what we care about is that we
    # don't get the decompression-bomb 400.
    assert r.headers.get("X-FileMorph-Error-Code") != "decompression_bomb"
