# SPDX-License-Identifier: AGPL-3.0-or-later
"""Target-size-eligible format list: web UI vs server, and every surface
that names the formats by hand.

The UI's hardcoded list once silently drifted from the server's — AVIF was
server-only for months before the "By target size" button offered it for
AVIF files too. This pins ``app.js``'s ``TARGET_SIZE_FORMATS`` array equal
to the Python set that actually gates the feature, plus the markup, the
rendered pages (both locales) and every hand-written claim (homepage FAQ,
/formats, /llms.txt, the OpenAPI form-field docs, /tools card) that
describes which formats hit an exact target size.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.tools_content import TOOLS_CONTENT

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
CONVERT_TOOL_HTML = (ROOT / "app/templates/partials/convert_tool.html").read_text(encoding="utf-8")

EN_AVIF_HINT = (
    "AVIF takes noticeably longer — a large photo can take a minute or more, "
    "so keep AVIF batches small."
)
DE_AVIF_HINT = (
    "AVIF dauert deutlich länger — ein großes Foto kann eine Minute oder länger "
    "brauchen, daher AVIF-Stapel klein halten."
)
EN_MODE_HINT = "JPEG, WebP and AVIF only."
DE_MODE_HINT = "Nur JPEG, WebP und AVIF."


# ── JS/Python parity ──────────────────────────────────────────────────────


def test_js_target_size_formats_matches_python_set():
    """app.js's TARGET_SIZE_FORMATS array must equal the Python
    TARGET_SIZE_FORMATS set in app/compressors/image.py — the set that
    actually gates target-size compression server-side."""
    # Without the plugin the Python set has no "avif" while app.js always
    # does — that would fail for an environment reason, not a product bug.
    # Mirrors the guard in tests/test_avif.py; the other tests here don't
    # need the plugin.
    pytest.importorskip("pillow_avif", reason="pillow-avif-plugin not installed")
    from app.compressors.image import TARGET_SIZE_FORMATS

    match = re.search(r"const TARGET_SIZE_FORMATS = \[(.*?)\];", APP_JS, re.S)
    assert match, "app.js lost its TARGET_SIZE_FORMATS constant"
    js_formats = set(re.findall(r"'([^']*)'", match.group(1)))
    assert js_formats == TARGET_SIZE_FORMATS


# ── Static markup/JS checks ───────────────────────────────────────────────


def test_app_js_shows_avif_hint_only_in_target_mode_with_an_avif_file():
    """Pins the toggle logic itself, not just the element id: visible only
    when target-size mode is shown AND a selected file is .avif."""
    assert re.search(
        r"getElementById\('target-size-avif-hint'\).*?"
        r"some\(f => getExtension\(f\.name\) === 'avif'\).*?"
        r"classList\.toggle\('hidden',\s*!\(showTarget && hasAvif\)\)",
        APP_JS,
        re.S,
    ), "app.js no longer ties #target-size-avif-hint to target mode + an AVIF file"


def test_clearing_the_selection_hides_the_target_size_section():
    """Clearing the files must go through updateQualityVisibility() (which
    hides the slider, the mode toggle and the target-size section incl. the
    AVIF hint) — it used to hide only the quality slider."""
    body = re.search(r"function clearAllFiles\(event\) \{(.*?)\n\}", APP_JS, re.S)
    assert body, "app.js lost clearAllFiles()"
    assert "updateQualityVisibility();" in body.group(1)


def test_convert_tool_partial_avif_hint_exists_and_starts_hidden():
    tag = re.search(r'<p id="target-size-avif-hint"[^>]*>', CONVERT_TOOL_HTML)
    assert tag, "convert_tool.html lost the #target-size-avif-hint element"
    css_class = re.search(r'class="([^"]*)"', tag.group(0))
    assert css_class and "hidden" in css_class.group(1).split(), (
        "#target-size-avif-hint must start hidden"
    )


# ── Rendered i18n leakage checks ──────────────────────────────────────────


def test_compress_page_avif_hint_and_mode_hint_localised(client):
    en = client.get("/en/compress").text
    de = client.get("/de/compress").text
    assert EN_AVIF_HINT in en and DE_AVIF_HINT not in en
    assert EN_MODE_HINT in en and DE_MODE_HINT not in en
    assert DE_AVIF_HINT in de and EN_AVIF_HINT not in de
    assert DE_MODE_HINT in de and EN_MODE_HINT not in de


def test_homepage_carries_avif_hint_both_locales(client):
    """The tool partial is embedded on the homepage too, so the same
    hint element (and its localised text) must render there as well."""
    en = client.get("/en/").text
    de = client.get("/de/").text
    assert 'id="target-size-avif-hint"' in en
    assert 'id="target-size-avif-hint"' in de
    assert EN_AVIF_HINT in en
    assert DE_AVIF_HINT in de


# ── Claim checks — every surface naming the target-size formats ───────────


def test_homepage_faq_exact_size_answer_names_avif(client):
    en = client.get("/en/").text
    de = client.get("/de/").text
    en_q = "Can I compress a file to an exact size?"
    de_q = "Kann ich eine Datei auf eine exakte Größe komprimieren?"
    en_match = re.search(re.escape(en_q) + r"</h3>\s*<p[^>]*>(.*?)</p>", en, re.S)
    de_match = re.search(re.escape(de_q) + r"</h3>\s*<p[^>]*>(.*?)</p>", de, re.S)
    assert en_match, f"FAQ question {en_q!r} not found on /en/"
    assert de_match, f"FAQ question {de_q!r} not found on /de/"
    assert "AVIF" in en_match.group(1)
    assert "AVIF" in de_match.group(1)


def test_formats_page_target_size_section_names_avif(client):
    en = client.get("/en/formats").text
    de = client.get("/de/formats").text
    en_start = en.index("Compress to a target size")
    en_section = en[en_start : en.index('<div class="grid', en_start)]
    de_start = de.index("Auf eine Zielgröße komprimieren")
    de_section = de[de_start : de.index('<div class="grid', de_start)]
    assert "AVIF" in en_section
    assert "AVIF" in de_section


def test_llms_txt_states_avif_target_size(client):
    llms = client.get("/llms.txt").text
    assert "compress JPEG, WebP and AVIF images to an exact target size" in llms


def test_llms_txt_compress_bullet_names_avif(client):
    """The "- [Compress an image or video]" bullet used to say "shrink a
    JPEG or WebP" — it must name AVIF too, next to the about-paragraph
    claim checked above."""
    llms = client.get("/llms.txt").text
    bullet = next(
        (ln for ln in llms.splitlines() if ln.startswith("- [Compress an image or video]")),
        "",
    )
    assert bullet, "llms.txt lost its '- [Compress an image or video]' bullet"
    assert "AVIF" in bullet


def test_openapi_target_size_kb_description_names_avif_both_endpoints(client):
    """The target_size_kb Form-field description on both /api/v1/compress
    and /api/v1/compress/batch must say AVIF, not just JPEG/WebP."""
    spec = client.get("/openapi.json").json()
    for path in ("/api/v1/compress", "/api/v1/compress/batch"):
        body = spec["paths"][path]["post"]["requestBody"]["content"]["multipart/form-data"]
        schema_name = body["schema"]["$ref"].rsplit("/", 1)[-1]
        props = spec["components"]["schemas"][schema_name]["properties"]
        assert "AVIF" in props["target_size_kb"]["description"], path


def test_tools_content_compress_target_card_names_avif():
    for locale in ("en", "de"):
        desc = TOOLS_CONTENT[locale]["cards"]["compress_target"]["desc"]
        assert "AVIF" in desc
