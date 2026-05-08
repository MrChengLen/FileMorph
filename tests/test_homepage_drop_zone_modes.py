# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drop-zone help text must carry both mode-specific blocks.

The convert and compress modes accept different input formats — convert
covers all source formats including audio and documents, while compress
only handles JPG/PNG/WebP/TIFF and MP4/AVI/MOV/MKV/WebM. The homepage
renders both lists side-by-side; `app/static/js/app.js::setMode()`
toggles their visibility. If a future refactor drops one of the two
elements, the user sees a stale or empty caption — this test fails first.
"""

from __future__ import annotations


def test_homepage_carries_both_supported_lists(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert 'id="supported-convert"' in html, "convert-mode caption missing"
    assert 'id="supported-compress"' in html, "compress-mode caption missing"


def test_compress_caption_lists_only_image_and_video_formats(client):
    """Compress mode must NOT advertise audio, document, or spreadsheet formats —
    those have no compressor. Adding them back would mislead the user."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    start = html.find('id="supported-compress"')
    assert start != -1
    end = html.find("</p>", start)
    block = html[start:end]

    for forbidden in ["MP3", "WAV", "FLAC", "OGG", "M4A", "DOCX", "PDF", "XLSX", "CSV"]:
        assert forbidden not in block, (
            f"compress-mode caption advertises {forbidden} but no compressor exists for it"
        )
