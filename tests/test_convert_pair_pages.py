# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 2 per-pair landing pages (/convert/<src>-to-<tgt>).

Guards: every curated pair renders in both locales with a working embedded
tool pre-set to the pair; uncurated/unsupported/malformed slugs 404 (so no
thin auto-pages); titles/metas stay in SERP range; the sitemap lists the
pairs with hreflang; the homepage still renders after the tool-card was
extracted into a shared partial; pages stay deployment-agnostic.

UX refactor guards (convert-pair tool constraints):
- Pair pages show only the source format in the supported-hint, not the
  full HEIC·JPG·PNG·… list.
- #file-input carries an ``accept`` attribute scoped to the source format.
- The Convert/Compress mode toggle is absent on pair pages (convert-only).
- Homepage still shows the full supported list and the mode toggle.
- Footer uses the new grouped-by-target layout; all 12 pairs still linked.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from app.core.convert_pairs import PAIR_CONTENT

_PAIRS = sorted(PAIR_CONTENT)


def _slug(pair):
    return f"{pair[0]}-to-{pair[1]}"


@pytest.mark.parametrize("pair", _PAIRS, ids=_slug)
@pytest.mark.parametrize("prefix", ["", "/en", "/de"])
def test_pair_page_renders(client, pair, prefix):
    r = client.get(f"{prefix}/convert/{_slug(pair)}")
    assert r.status_code == 200, f"{prefix}/convert/{_slug(pair)} -> {r.status_code}"
    # embeds the real working tool
    assert 'id="drop-zone"' in r.text and 'id="target-format"' in r.text
    # pre-set to this pair (app.js reads these; not disabled)
    assert f'data-preset-source="{pair[0]}"' in r.text
    assert f'data-preset-target="{pair[1]}"' in r.text
    # has an H1 and a visible FAQ (GEO)
    assert "<h1" in r.text
    assert "<h3" in r.text


@pytest.mark.parametrize("pair", _PAIRS, ids=_slug)
@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_pair_title_and_meta_in_serp_range(client, pair, prefix):
    r = client.get(f"{prefix}/convert/{_slug(pair)}")
    assert r.status_code == 200
    title = re.search(r"<title[^>]*>([^<]+)</title>", r.text, re.IGNORECASE).group(1).strip()
    # double-quote-only so apostrophes in the meta (e.g. "don't") don't truncate
    # the captured string and under-measure its length.
    meta = (
        re.search(r'<meta\s+name="description"\s+content="([^"]+)"', r.text, re.IGNORECASE)
        .group(1)
        .strip()
    )
    assert len(title) <= 60, f"{prefix}/{_slug(pair)} title {len(title)}: {title!r}"
    assert len(meta) <= 160, f"{prefix}/{_slug(pair)} meta {len(meta)}: {meta!r}"
    assert len(title) >= 10 and len(meta) >= 50


def test_pair_page_localised(client):
    """The same slug serves localized content per locale prefix."""
    en = client.get("/en/convert/jpg-to-pdf").text
    de = client.get("/de/convert/jpg-to-pdf").text
    assert "Convert JPG to PDF" in en
    assert "JPG in PDF umwandeln" in de
    assert "Wandle JPG in PDF um" in de  # body content, not just the heading


def test_pair_page_has_related_links(client):
    r = client.get("/en/convert/jpg-to-pdf")
    assert r.status_code == 200
    # same-target family first — png-to-pdf / heic-to-pdf should be linked
    assert "/convert/png-to-pdf" in r.text
    assert "/convert/heic-to-pdf" in r.text


def test_pair_page_deployment_agnostic(client):
    """Pair pages ship in the public OSS repo — no hardcoded SaaS host."""
    r = client.get("/en/convert/heic-to-jpg")
    assert "filemorph.io" not in r.text


# ── 404 / thin-content guards ────────────────────────────────────────────────


def test_unsupported_pair_404(client):
    """A slug that isn't curated (no content) must 404, even if it parses."""
    r = client.get("/convert/jpg-to-mp3")
    assert r.status_code == 404


def test_malformed_slug_404(client):
    r = client.get("/convert/notapair")
    assert r.status_code == 404


def test_unknown_pair_404(client):
    r = client.get("/convert/zzz-to-qqq")
    assert r.status_code == 404


# ── sitemap ──────────────────────────────────────────────────────────────────


def test_sitemap_lists_pair_pages_with_hreflang(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "xhtml": "http://www.w3.org/1999/xhtml",
    }
    locs = {
        (u.find("sm:loc", ns).text or "")
        for u in root.findall("sm:url", ns)
        if u.find("sm:loc", ns) is not None
    }
    # every curated pair present as x-default + de + en
    for pair in _PAIRS:
        slug = _slug(pair)
        assert any(loc.endswith(f"/convert/{slug}") for loc in locs), f"missing x-default {slug}"
        assert any(loc.endswith(f"/en/convert/{slug}") for loc in locs), f"missing /en {slug}"
        assert any(loc.endswith(f"/de/convert/{slug}") for loc in locs), f"missing /de {slug}"

    # each pair url block carries the 3 hreflang alternates
    for u in root.findall("sm:url", ns):
        loc = u.find("sm:loc", ns).text or ""
        if "/convert/" in loc:
            hreflangs = {a.attrib.get("hreflang") for a in u.findall("xhtml:link", ns)}
            assert hreflangs == {"x-default", "de", "en"}, f"{loc} hreflangs {hreflangs}"
            break


# ── homepage regression (tool-card extracted into a shared partial) ──────────


def test_homepage_still_has_working_tool(client):
    """The convert tool was extracted into _components/convert_tool.html and is
    {% include %}-d by index.html — the homepage must still render it, with an
    empty preset (no pre-selected target)."""
    r = client.get("/en/")
    assert r.status_code == 200
    assert 'id="drop-zone"' in r.text
    assert 'id="target-format"' in r.text
    assert 'data-preset-target=""' in r.text  # homepage = no preset
    # homepage-specific sections still present
    assert 'id="self-hosted"' in r.text
    assert "Frequently asked questions" in r.text


# ── global footer links (every page) ─────────────────────────────────────────


def test_footer_lists_all_pair_pages(client):
    """The footer (rendered on every page via base.html) links every curated
    pair — internal link graph + discovery."""
    r = client.get("/en/")
    assert r.status_code == 200
    assert "Popular conversions" in r.text
    for pair in _PAIRS:
        assert f'href="/en/convert/{_slug(pair)}"' in r.text, f"footer missing {_slug(pair)}"


def test_footer_links_localized(client):
    r = client.get("/de/")
    assert "Beliebte Konvertierungen" in r.text
    assert 'href="/de/convert/jpg-to-pdf"' in r.text


def test_footer_present_on_pair_pages(client):
    """The footer (with the pair links) appears on the pair pages themselves."""
    r = client.get("/en/convert/heic-to-jpg")
    assert "Popular conversions" in r.text
    assert 'href="/en/convert/png-to-jpg"' in r.text


# ── UX refactor: pair-page tool constraints ──────────────────────────────────


def test_pair_page_supported_hint_is_source_only(client):
    """On a pair page the supported hint shows ONLY the source format (e.g.
    'JPG' on /convert/jpg-to-pdf), not the full HEIC·JPG·PNG·… list."""
    r = client.get("/en/convert/jpg-to-pdf")
    assert r.status_code == 200
    # Source format present in the scoped hint
    assert "Supported: JPG" in r.text
    # Full multi-format list must NOT appear (it's homepage-only)
    assert "HEIC · JPG · PNG" not in r.text


def test_pair_page_file_input_has_scoped_accept(client):
    """On a pair page #file-input carries an accept attribute for the source
    format so the OS file picker filters to the right type."""
    r = client.get("/en/convert/jpg-to-pdf")
    assert r.status_code == 200
    assert 'accept=".jpg,.jpeg,image/jpeg"' in r.text


def test_pair_page_compress_toggle_absent(client):
    """The Convert/Compress mode toggle must not appear on pair pages
    (a conversion pair is convert-only)."""
    r = client.get("/en/convert/jpg-to-pdf")
    assert r.status_code == 200
    assert 'id="btn-mode-compress"' not in r.text
    assert 'id="btn-mode-convert"' not in r.text


def test_homepage_still_has_full_supported_list_and_toggle(client):
    """The homepage retains the full supported-format list and the mode
    toggle — only pair pages are constrained."""
    r = client.get("/en/")
    assert r.status_code == 200
    # Full list present
    assert "HEIC · JPG · PNG" in r.text
    # Mode toggle present
    assert 'id="btn-mode-convert"' in r.text
    assert 'id="btn-mode-compress"' in r.text
    # No scoped accept on homepage file input
    assert 'accept="' not in r.text


def test_footer_grouped_layout_links_all_pairs(client):
    """Footer uses the grouped layout (group headings present) and still
    links all curated pairs — internal link equity is fully preserved."""
    r = client.get("/en/")
    assert r.status_code == 200
    # Group headings use arrow notation
    assert "→ PDF" in r.text
    assert "→ JPG" in r.text
    # Every pair must still be reachable
    for pair in _PAIRS:
        assert f'href="/en/convert/{_slug(pair)}"' in r.text, (
            f"footer missing grouped link for {_slug(pair)}"
        )


def test_convert_tool_partial_is_translated_on_de(client):
    """Regression guard for the i18n extraction trap: the convert tool lives in
    a Jinja partial. babel's extractor prunes underscore-prefixed dirs, so the
    partial must stay in a non-underscore dir (app/templates/partials/) to be
    extracted — otherwise its `_()` strings silently fall back to English on
    /de/ (this regressed when the card was first moved into _components/).
    Assert a tool string is genuinely translated on /de/."""
    de = client.get("/de/").text
    assert "Drag & drop your files here" not in de, (
        "convert-tool partial is not translated on /de/ — is it back in an "
        "underscore dir, or is babel not scanning app/templates/partials/?"
    )
    assert "Unterstützt:" in client.get("/de/convert/jpg-to-pdf").text


def test_pair_page_hides_target_format_dropdown(client):
    """On a pair page the target is fixed by the URL, so the Target Format
    label/dropdown must not be shown — but the <select> stays in the DOM
    (hidden) because app.js reads #target-format. The homepage keeps the
    labelled, visible dropdown."""
    pair = client.get("/en/convert/jpg-to-pdf").text
    home = client.get("/en/").text
    # Select element stays for app.js, but the visible label is gone on pairs.
    assert 'id="target-format"' in pair
    assert ">Target Format<" not in pair
    # Homepage keeps the labelled dropdown.
    assert ">Target Format<" in home
