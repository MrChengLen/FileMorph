# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drop-zone help text must carry both mode-specific blocks.

The convert and compress modes accept different input formats — convert
covers every registered source format, while compress covers only the
image/video formats listed under "compression" in /api/v1/formats (a
shorter, changing list — enumerating it here would go stale, see
test_convert_caption_matches_formats_api / test_compress_caption_matches_formats_api
below, which compare the rendered captions against that live API instead).
The homepage renders both lists side-by-side; `app/static/js/app.js::setMode()`
toggles their visibility. If a future refactor drops one of the two
elements, the user sees a stale or empty caption — this test fails first.
"""

from __future__ import annotations

import pytest


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


# ── captions must match the live registry, not a hand-kept snapshot ────────
#
# Both `#supported-convert` and `#supported-compress` are meant to list
# *every* format the tool actually accepts in that mode. Rather than pin a
# second hardcoded list here (which would just be one more place to forget
# to update), derive the expectation from /api/v1/formats — the same source
# of truth the tool itself uses — so adding a converter without updating the
# caption fails CI instead of silently under-advertising the feature.

# Second spelling of the same format — the caption shows one token per
# format, not every registered alias.
_ALIAS = {"jpeg": "jpg", "tif": "tiff", "htm": "html"}


def _alias(fmt: str) -> str:
    return _ALIAS.get(fmt, fmt)


def _caption_tokens(html: str, element_id: str) -> set[str]:
    """Extract the lowercased format tokens out of a `<p id="...">` caption
    block: slice from the `>` closing the opening tag to the matching
    `</p>`, split on `<br>`, drop the leading `Supported:` / `Unterstützt:`
    label, then split each line on `·`."""
    start = html.index(f'id="{element_id}"')
    tag_end = html.index(">", start) + 1
    block_end = html.index("</p>", tag_end)
    block = html[tag_end:block_end]

    tokens: set[str] = set()
    for line in block.split("<br>"):
        line = line.strip()
        for label in ("Supported:", "Unterstützt:"):
            if line.startswith(label):
                line = line[len(label) :]
                break
        for token in line.split("·"):
            token = token.strip().lower()
            if token:
                tokens.add(token)
    return tokens


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_convert_caption_matches_formats_api(client, prefix):
    caption = _caption_tokens(client.get(f"{prefix}/").text, "supported-convert")
    conversions = client.get("/api/v1/formats").json()["conversions"]
    expected = {_alias(s) for s in conversions}
    missing, extra = expected - caption, caption - expected
    assert caption == expected, (
        f"supported-convert caption ({prefix}) drifted from /api/v1/formats — "
        f"missing: {sorted(missing)}, extra: {sorted(extra)}"
    )


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_compress_caption_matches_formats_api(client, prefix):
    caption = _caption_tokens(client.get(f"{prefix}/").text, "supported-compress")
    compression = client.get("/api/v1/formats").json()["compression"]
    expected = {_alias(s) for s in compression["image"] + compression["video"]}
    missing, extra = expected - caption, caption - expected
    assert caption == expected, (
        f"supported-compress caption ({prefix}) drifted from /api/v1/formats — "
        f"missing: {sorted(missing)}, extra: {sorted(extra)}"
    )
