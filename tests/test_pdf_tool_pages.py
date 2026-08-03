# SPDX-License-Identifier: AGPL-3.0-or-later
"""/pdf/{split,extract,compress} tool pages — the ungated, core-OSS PDF
structural-operation landing pages (unlike the flag-gated /redact).

Guards: every tool renders in all three locale mounts with the real, working
tool embedded (data-tool/data-endpoint, visible FAQ <h3>s for GEO);
titles/metas stay in SERP range; content is plain bilingual data (not
gettext, see app/core/pdf_tools_content.py), so DE vs EN must genuinely
differ; an uncurated tool slug 404s (the content lookup IS the route
whitelist); per-tool controls are scoped to their own page; the sitemap /
llms.txt / footer / homepage / /formats surfaces all discover the three
pages; pages stay deployment-agnostic; and the honest-compress wording
(project motto: never fake a "success") is present on the compress page.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.core.pdf_tools_content import PDF_TOOL_CONTENT, get_pdf_tool_content

_TOOLS = sorted(PDF_TOOL_CONTENT)  # ["compress", "extract", "split"]


@pytest.mark.parametrize("tool", _TOOLS)
@pytest.mark.parametrize("prefix", ["", "/en", "/de"])
def test_pdf_tool_page_renders(client, tool, prefix):
    r = client.get(f"{prefix}/pdf/{tool}")
    assert r.status_code == 200, f"{prefix}/pdf/{tool} -> {r.status_code}"
    assert 'id="pdf-tool"' in r.text
    assert f'data-tool="{tool}"' in r.text
    assert f'data-endpoint="/api/v1/pdf/{tool}"' in r.text
    assert "<h1" in r.text
    assert "<h3" in r.text  # visible FAQ headings (GEO)


@pytest.mark.parametrize("tool", _TOOLS)
@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_pdf_tool_title_and_meta_in_serp_range(client, tool, prefix):
    r = client.get(f"{prefix}/pdf/{tool}")
    assert r.status_code == 200
    title = re.search(r"<title[^>]*>([^<]+)</title>", r.text, re.IGNORECASE).group(1).strip()
    # double-quote-only so apostrophes in the meta (e.g. "there's") don't
    # truncate the captured string and under-measure its length.
    meta = (
        re.search(r'<meta\s+name="description"\s+content="([^"]+)"', r.text, re.IGNORECASE)
        .group(1)
        .strip()
    )
    assert len(title) <= 60, f"{prefix}/pdf/{tool} title {len(title)}: {title!r}"
    assert len(meta) <= 160, f"{prefix}/pdf/{tool} meta {len(meta)}: {meta!r}"
    assert len(title) >= 10 and len(meta) >= 50


# ── DE/EN localisation ───────────────────────────────────────────────────────


@pytest.mark.parametrize("tool", _TOOLS)
def test_pdf_tool_page_localised(client, tool):
    """Content lives as plain bilingual data (pdf_tools_content.py), not
    gettext — h1 AND a body string (hero) must genuinely differ per locale,
    not just repeat the English string on /de/."""
    en = PDF_TOOL_CONTENT[tool]["en"]
    de = PDF_TOOL_CONTENT[tool]["de"]
    en_html = client.get(f"/en/pdf/{tool}").text
    de_html = client.get(f"/de/pdf/{tool}").text
    assert en["h1"] in en_html
    assert de["h1"] in de_html
    assert en["h1"] != de["h1"]
    assert en["hero"] in en_html
    assert de["hero"] in de_html
    assert en["hero"] != de["hero"]


def test_split_page_localised_with_hardcoded_strings(client):
    """Hardcoded (not module-derived) strings, mirroring
    test_convert_pair_pages.py::test_pair_page_localised — catches a
    copy-paste bug that would corrupt PDF_TOOL_CONTENT itself and so slip
    past the module-derived comparison above."""
    en = client.get("/en/pdf/split").text
    de = client.get("/de/pdf/split").text
    assert "Split a PDF into pages" in en
    assert "PDF in Einzelseiten aufteilen" in de
    assert "Ein mehrseitiges PDF in einzelne Seiten aufteilen" in de  # body, not just heading


# ── 404 / route-whitelist guards ─────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/pdf/rotate", "/pdf/x-to-y", "/en/pdf/merge"])
def test_unknown_pdf_tool_404(client, path):
    """An uncurated tool slug 404s on all mounts — get_pdf_tool_content()
    returning None IS the route whitelist, so no thin/hollow page can ever
    render. Trailing-slash variants aren't asserted here: FastAPI
    307-redirects them before the route body runs."""
    assert client.get(path).status_code == 404, path


def test_get_pdf_tool_content_unknown_tool_returns_none():
    assert get_pdf_tool_content("rotate", "en") is None


# ── accept scoping + per-tool controls ───────────────────────────────────────


@pytest.mark.parametrize("tool", _TOOLS)
def test_pdf_tool_file_input_accepts_pdf_only(client, tool):
    r = client.get(f"/en/pdf/{tool}")
    assert r.status_code == 200
    assert 'accept=".pdf,application/pdf"' in r.text


def test_extract_page_has_pages_input_only(client):
    r = client.get("/en/pdf/extract")
    assert 'id="pdf-pages"' in r.text
    assert 'id="pdf-target-size"' not in r.text


def test_compress_page_has_target_size_input_only(client):
    r = client.get("/en/pdf/compress")
    assert 'id="pdf-target-size"' in r.text
    assert 'id="pdf-pages"' not in r.text


def test_split_page_has_zip_and_10000_notice_and_no_tool_specific_inputs(client):
    r = client.get("/en/pdf/split")
    assert 'id="pdf-pages"' not in r.text
    assert 'id="pdf-target-size"' not in r.text
    assert "ZIP" in r.text
    assert "10,000" in r.text


def test_pdf_honest_note_placeholder_present_on_all_three_pages(client):
    """#pdf-honest-note is a shared, pre-styled (amber, hidden-by-default)
    placeholder in the ONE shared partial's Result block — not gated per
    tool (see partials/pdf_tool.html). pdf-tools.js only *shows* it for
    compress (showCompressHonesty); split/extract never populate or reveal
    it. Its presence in the markup on all three pages is correct, not a
    honesty leak — only visibility is tool-scoped, at runtime, client-side."""
    for tool in _TOOLS:
        assert 'id="pdf-honest-note"' in client.get(f"/en/pdf/{tool}").text


# ── discovery surfaces ───────────────────────────────────────────────────────


def test_sitemap_lists_pdf_tool_pages_with_hreflang(client):
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
    for tool in _TOOLS:
        path = f"/pdf/{tool}"
        assert any(loc.endswith(path) for loc in locs), f"missing x-default {path}"
        assert any(loc.endswith(f"/en{path}") for loc in locs), f"missing /en {path}"
        assert any(loc.endswith(f"/de{path}") for loc in locs), f"missing /de {path}"

    # every URL block for a /pdf/ page carries exactly the 3 hreflang alternates
    checked = 0
    for u in root.findall("sm:url", ns):
        loc = u.find("sm:loc", ns).text or ""
        if "/pdf/" in loc:
            hreflangs = {a.attrib.get("hreflang") for a in u.findall("xhtml:link", ns)}
            assert hreflangs == {"x-default", "de", "en"}, f"{loc} hreflangs {hreflangs}"
            checked += 1
    assert checked == len(_TOOLS) * 3  # 3 tools x (x-default + de + en) URL entries


def test_llms_txt_lists_pdf_tool_pages(client):
    llms = client.get("/llms.txt").text
    for tool in _TOOLS:
        assert f"/pdf/{tool}" in llms


def test_footer_links_localized_to_pdf_tools(client):
    en = client.get("/en/").text
    de = client.get("/de/").text
    for tool in _TOOLS:
        assert f'href="/en/pdf/{tool}"' in en
        assert f'href="/de/pdf/{tool}"' in de


def test_homepage_teaser_links_to_pdf_tools(client):
    r = client.get("/en/")
    assert r.status_code == 200
    for tool in _TOOLS:
        assert f"/pdf/{tool}" in r.text


def test_formats_page_links_to_pdf_tools(client):
    r = client.get("/en/formats")
    assert r.status_code == 200
    for tool in _TOOLS:
        assert f"/pdf/{tool}" in r.text


# ── deployment-agnostic + honest-compress wording ────────────────────────────


@pytest.mark.parametrize("tool", _TOOLS)
def test_pdf_tool_page_deployment_agnostic(client, tool):
    """Tool pages ship in the public OSS repo — no hardcoded SaaS host."""
    r = client.get(f"/en/pdf/{tool}")
    assert "filemorph.io" not in r.text


def test_compress_page_states_honest_limits(client):
    """Project motto: never fake a "success". The compress page's own prose
    must say, in both locales, that the achieved size is always shown and a
    shortfall is stated plainly — mirrors pdf-tools.js::showCompressHonesty
    (which reads X-FileMorph-Converged / X-FileMorph-Recompressible-Images)."""
    en = client.get("/en/pdf/compress").text
    de = client.get("/de/pdf/compress").text
    assert "the tool always shows the size it actually achieved" in en
    assert "das Tool zeigt immer die tatsächlich erreichte Größe" in de


# ── DOM-id contract between pdf-tools.js and the partial ─────────────────────

# Ids that exist only on specific tools' pages; every other id the script
# queries must be present on all three.
_TOOL_SCOPED_IDS = {
    "pdf-pages": {"extract"},
    "pdf-pages-warn": {"extract"},
    "pdf-target-size": {"compress"},
}


def test_partial_provides_every_dom_id_the_js_queries(client):
    """pdf-tools.js has no runtime test — pin its DOM contract instead: every
    id the script queries via $('...') must exist in the rendered page(s) of
    the tool(s) it applies to, so a partial rename cannot break the tool
    silently."""
    js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "pdf-tools.js"
    ids = set(re.findall(r"\$\('([a-z-]+)'\)", js_path.read_text(encoding="utf-8")))
    assert ids, "id-extraction regex matched nothing — did the $ helper change?"
    pages = {tool: client.get(f"/pdf/{tool}").text for tool in _TOOLS}
    for dom_id in sorted(ids):
        for tool in _TOOL_SCOPED_IDS.get(dom_id, set(_TOOLS)):
            assert f'id="{dom_id}"' in pages[tool], f"#{dom_id} missing on /pdf/{tool}"
