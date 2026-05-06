# SPDX-License-Identifier: AGPL-3.0-or-later
"""H3 — Format-registry cardinality regression guard.

The README and homepage both promise "30+ formats." If a refactor silently
drops a converter or a `@register` decorator goes stale, the public claim
breaks without a CI signal. These tests pin the floor.
"""

from __future__ import annotations

from app.converters.registry import get_supported_conversions

# Formats specifically advertised on the homepage drop-zone help text
# (`app/templates/index.html`). If a homepage edit adds a format here,
# extend this list and ensure a converter is registered for it.
_HOMEPAGE_ADVERTISED = {
    # images
    "heic",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "bmp",
    "tiff",
    "tif",
    "gif",
    # documents
    "docx",
    "pdf",
    "txt",
    "md",
    # spreadsheets
    "xlsx",
    "csv",
    "json",
    # video
    "mp4",
    "mov",
    "avi",
    "mkv",
    "webm",
    # audio
    "mp3",
    "wav",
    "flac",
    "ogg",
    "m4a",
}


def _all_formats() -> set[str]:
    """Return every format that appears as either a source or target."""
    m = get_supported_conversions()
    return set(m.keys()) | {tgt for tgts in m.values() for tgt in tgts}


def test_supported_conversions_count_meets_30plus_promise() -> None:
    """README + pricing copy say '30+ formats'. Pin the floor at 30."""
    assert len(_all_formats()) >= 30, (
        f"Public copy promises 30+ formats; registry has {len(_all_formats())}: {sorted(_all_formats())}"
    )


def test_total_pair_count_indicates_real_breadth() -> None:
    """Defence-in-depth: 30 unique formats with only 30 pairs would be a single
    chain (e.g., A→B→C→…). The promise implies real breadth — many formats
    interconvertible. Pin a floor on total pairs."""
    m = get_supported_conversions()
    pairs = sum(len(tgts) for tgts in m.values())
    assert pairs >= 100, f"Expected ≥100 conversion pairs, got {pairs}"


def test_every_homepage_advertised_format_is_registered() -> None:
    """Every format the homepage drop-zone names is supported as either a
    source or a target. If marketing adds a format to the list without a
    converter, this test fails until a converter ships."""
    available = _all_formats()
    missing = _HOMEPAGE_ADVERTISED - available
    assert not missing, f"Homepage advertises but registry misses: {sorted(missing)}"
