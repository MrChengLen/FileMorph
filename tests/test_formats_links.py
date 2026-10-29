# SPDX-License-Identifier: AGPL-3.0-or-later
"""/formats links every conversion (2026-10-28).

A pair with a page of its own links that page (/convert/<pair>, and
/convert/video-to-gif for video → GIF); every other pair links the homepage
converter pre-set by "#convert=<src>-to-<tgt>", a fragment the server never
sees, so no thin pages appear for search engines. app.js applies the fragment
only for a pair the live format list has, writes its notice as plain text, and
never converts a file that can't reach a preset's target to another target
without a word (product-ux.md #1). There is no JS runner in the repo, so the
app.js guards are pinned on its source, like tests/test_homepage_quick_actions.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.converters.registry import get_public_conversions
from app.converters.video import _VIDEO_FORMATS
from app.core import catalog
from app.core.convert_pairs import _ACCEPT

_APP_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js"


def _matrix(html: str) -> str:
    """The conversion matrix of /formats, without the compression section."""
    start = html.index("<!-- Conversion matrix")
    return html[start : html.index("<!-- Compression", start)]


def _pairs() -> set[tuple[str, str]]:
    """The conversions the matrix lists: other spellings (JPEG, TIF, HTM)
    under the first name, each conversion once (tests/test_format_search.py)."""
    same = {"jpeg": "jpg", "tif": "tiff", "htm": "html"}
    pairs = set()
    for src, targets in get_public_conversions().items():
        for tgt in targets:
            pair = (same.get(src, src), same.get(tgt, tgt))
            if pair[0] != pair[1]:
                pairs.add(pair)
    return pairs


def _js_function(source: str, name: str) -> str:
    """Body of a top-level ``function name(`` in app.js, up to the next one."""
    start = source.index(f"function {name}(")
    end = source.find("\nfunction ", start + 1)
    return source[start : end if end != -1 else None]


# ── /formats ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["", "/en", "/de"])
def test_every_conversion_is_a_link(client, prefix):
    matrix = _matrix(client.get(f"{prefix}/formats").text)
    pairs = _pairs()
    hrefs = re.findall(r'<a href="([^"]+)"', matrix)
    assert len(hrefs) == len(pairs) == len(set(re.findall(r'data-pair="([^"]+)"', matrix)))
    assert "<span" not in matrix
    for href in hrefs:
        if "#convert=" in href:
            base, _, pair = href.partition("#convert=")
            src, _, tgt = pair.partition("-to-")
            assert base == f"{prefix}/" and (src, tgt) in pairs, href
        else:
            assert href.startswith(f"{prefix}/convert/"), href


def test_page_links_on_formats_lead_to_pages(client):
    matrix = _matrix(client.get("/en/formats").text)
    paths = {href for href in re.findall(r'<a href="([^"#]+)"', matrix)}
    assert paths
    for path in sorted(paths):
        assert client.get(path).status_code == 200, path


def test_video_to_gif_chips_link_the_video_to_gif_page(client):
    matrix = _matrix(client.get("/en/formats").text)
    assert matrix.count('href="/en/convert/video-to-gif"') == len(_VIDEO_FORMATS)
    assert "#convert=mp4-to-gif" not in matrix


def test_every_pair_page_is_linked_once(client):
    matrix = _matrix(client.get("/en/formats").text)
    for page in catalog.pages(kind="convert"):
        assert matrix.count(f'href="/en{page.path}"') == 1, page.path


def test_chips_name_the_conversion_for_screen_readers(client):
    assert 'aria-label="XLSX in CSV umwandeln"' in client.get("/de/formats").text
    assert 'aria-label="Convert XLSX to CSV"' in client.get("/en/formats").text


# ── the converter pages ───────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/en/", "/en/convert/jpg-to-pdf", "/en/convert/video-to-gif"])
def test_converter_pages_carry_the_preset_notice(client, path):
    html = client.get(path).text
    # The hidden attribute, not the class: space-y-5 skips it (no extra gap).
    assert '<p id="preset-notice" role="status" hidden' in html
    assert 'id="preset-clear" href="/en/"' in html
    assert '"presetReady"' in html and '"presetMismatch"' in html


def test_preset_texts_are_translated(client):
    html = client.get("/de/").text
    for german in (
        "Voreingestellt: {src} in {tgt}. Wähle deine {src}-Datei.",
        "voreingestellt ist aber {src} in {tgt}",
        "lässt sich nicht in {tgt} umwandeln",
        "— Zielformat wählen —",
        "— erst eine Datei wählen —",
    ):
        assert german in html, german


# ── app.js ────────────────────────────────────────────────────────────────────


def test_app_js_applies_only_pairs_the_format_list_has():
    body = _js_function(_APP_JS.read_text(encoding="utf-8"), "applyHashPreset")
    assert "new URLSearchParams(location.hash.slice(1)).get('convert')" in body
    assert "/^([a-z0-9]+)-to-([a-z0-9]+)$/" in body
    # Own target lists only: a prototype key such as "constructor" has none.
    assert "const targets = supportedConversions[src];" in body
    assert "if (!Array.isArray(targets) || !targets.includes(tgt)) return;" in body
    # A conversion preset, like a pair page: convert mode, no mode toggle.
    assert "setMode('convert')" in body and "getElementById('mode-toggle')" in body
    assert "PRESET_ACCEPT[src]" in body


def test_app_js_writes_the_preset_notice_as_plain_text():
    body = _js_function(_APP_JS.read_text(encoding="utf-8"), "showPresetNotice")
    assert "text.textContent = message" in body
    assert "box.hidden = false" in body
    assert "innerHTML" not in body


def test_app_js_never_swaps_in_another_target_silently():
    source = _APP_JS.read_text(encoding="utf-8")
    single = _js_function(source, "updateTargetFormats")
    assert "select.insertBefore(choosePlaceholder(), select.firstChild)" in single
    assert "select.value = ''" in single and "presetMismatch" in single
    # No targets at all: the list shows, saying so, instead of staying hidden.
    assert single.count("select.classList.remove('hidden')") == 2
    batch = _js_function(source, "renderFileList")
    assert "perRowSelect.insertBefore(choosePlaceholder(), perRowSelect.firstChild)" in batch


@pytest.mark.parametrize("function", ["setFiles", "removeFile", "clearAllFiles", "setMode"])
def test_app_js_resets_the_preset_state_for_each_selection(function):
    """A notice or an unhidden list from the last file never outlives it."""
    body = _js_function(_APP_JS.read_text(encoding="utf-8"), function)
    assert "resetPresetUi();" in body


def test_app_js_waits_for_the_format_list_before_a_preset():
    source = _APP_JS.read_text(encoding="utf-8")
    assert "const formatsLoaded = init();" in source
    assert "formatsLoaded.then(applyHashPreset)" in source
    # A fragment change can't retarget a file that is already chosen, and a
    # page with a preset mode (/compress) takes no conversion preset.
    assert "if (!selectedFiles.length) applyHashPreset();" in source
    assert "if (!presetTarget && !presetMode) {" in source


def test_preset_accept_mirrors_the_pair_pages():
    """The picker filter a "#convert=" link sets is the one a pair page sets."""
    source = _APP_JS.read_text(encoding="utf-8")
    body = re.search(r"const PRESET_ACCEPT = \{(.*?)\};", source, re.S).group(1)
    assert dict(re.findall(r"(\w+): '([^']*)'", body)) == _ACCEPT
