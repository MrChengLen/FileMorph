# SPDX-License-Identifier: AGPL-3.0-or-later
"""CI gate: every registered conversion pair stays under a ceiling on a tiny
sample, so we catch regressions if a converter starts hanging or pulling
in a heavy dependency.

Scope is intentionally narrow:
  * Only image pairs (PIL-only — no ffmpeg dependency on the runner).
  * Smallest sample size (~100 KB).
  * Single iteration per pair.
  * Generous threshold (5 s) — this is a sanity check, not a perf regression
    benchmark. Use ``scripts/bench_conversions.py`` for that.

Pairs whose source format requires a missing dependency (HEIC needs
pillow-heif) are skipped, not failed — same dependency profile as production.
"""

from __future__ import annotations

import time

import pytest

from app.converters.registry import get_supported_conversions


def _image_pairs() -> list[tuple[str, str]]:
    """Return all (src, tgt) pairs whose source is a PIL-buildable image."""
    pil_buildable = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "gif", "ico"}
    supported = get_supported_conversions()
    return [(s, t) for s, ts in supported.items() if s in pil_buildable for t in ts]


@pytest.fixture(scope="module")
def smoke_sample_path(tmp_path_factory):
    """Reusable ~100 KB high-entropy JPEG. Module-scoped so we build once."""
    from PIL import Image

    tmp = tmp_path_factory.mktemp("bench_smoke")
    img = Image.new("RGB", (700, 700))
    pixels = img.load()
    for x in range(700):
        for y in range(700):
            pixels[x, y] = (
                (x * 7 + y * 3) % 256,
                (x * 13 + y * 11) % 256,
                (x * 5 + y * 17) % 256,
            )
    path = tmp / "sample.jpg"
    img.save(str(path), format="JPEG", quality=85)
    return path


def _build_sample_for_format(src_fmt: str, tmp_path):
    """Convert the JPEG seed into the target source format via PIL."""
    from PIL import Image

    fmt_map = {
        "jpg": "JPEG",
        "jpeg": "JPEG",
        "png": "PNG",
        "webp": "WEBP",
        "bmp": "BMP",
        "tiff": "TIFF",
        "tif": "TIFF",
        "gif": "GIF",
        "ico": "ICO",
    }
    pil_fmt = fmt_map.get(src_fmt)
    if pil_fmt is None:
        return None

    img = Image.new("RGB", (300, 300))
    pixels = img.load()
    for x in range(300):
        for y in range(300):
            pixels[x, y] = (
                (x * 7 + y * 3) % 256,
                (x * 13 + y * 11) % 256,
                (x * 5 + y * 17) % 256,
            )
    path = tmp_path / f"sample.{src_fmt}"

    if pil_fmt == "ICO":
        img.resize((128, 128)).save(str(path), format=pil_fmt)
    elif pil_fmt == "GIF":
        img.convert("P", palette=Image.ADAPTIVE).save(str(path), format=pil_fmt)
    else:
        img.save(str(path), format=pil_fmt, quality=85) if pil_fmt in (
            "JPEG",
            "WEBP",
        ) else img.save(str(path), format=pil_fmt)
    return path


SMOKE_THRESHOLD_S = 5.0


@pytest.mark.parametrize("src,tgt", _image_pairs())
def test_image_pair_completes_under_threshold(client, auth_headers, tmp_path, src, tgt):
    """Each registered image pair must convert a small sample in < 5 s.

    Threshold is generous on purpose — this is a regression sanity check, not
    a perf benchmark. Real perf numbers come from
    ``scripts/bench_conversions.py``.
    """
    sample = _build_sample_for_format(src, tmp_path)
    if sample is None:
        pytest.skip(f"could not build {src} sample (PIL backend missing)")

    sample_bytes = sample.read_bytes()

    t0 = time.perf_counter()
    res = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": (sample.name, sample_bytes, "application/octet-stream")},
        data={"target_format": tgt},
    )
    dt = time.perf_counter() - t0

    assert res.status_code == 200, f"{src}->{tgt} failed: {res.status_code} {res.text[:200]}"
    assert dt < SMOKE_THRESHOLD_S, f"{src}->{tgt} took {dt:.2f}s, threshold {SMOKE_THRESHOLD_S}s"
    assert len(res.content) > 0, f"{src}->{tgt} returned empty body"
