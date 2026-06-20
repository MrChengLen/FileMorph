# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 2 per-pair landing pages (/convert/<src>-to-<tgt>).

Guards: every curated pair renders in both locales with a working embedded
tool pre-set to the pair; uncurated/unsupported/malformed slugs 404 (so no
thin auto-pages); titles/metas stay in SERP range; the sitemap lists the
pairs with hreflang; the homepage still renders after the tool-card was
extracted into a shared partial; and pages stay deployment-agnostic.
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
