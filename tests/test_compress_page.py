# SPDX-License-Identifier: AGPL-3.0-or-later
"""/compress — the image/video target-size compression landing page (IA
rework PR 4, ``docs-internal/ia-navigation-konzept.md``).

Guards: renders in all three locale mounts with the real, working tool
embedded (the shared ``partials/convert_tool.html``) pre-set to Compress mode
via ``data-preset-mode`` (CSP-safe: a data-attribute read by ``app.js``, not
inline JS) — and that hook is a no-op everywhere else, including the
homepage; titles/metas stay in SERP range and deliberately never say "pdf"
(cannibalization guard — the PDF slice of this query space stays on
``/pdf/compress``); content is plain bilingual data (not gettext, see
app/core/compress_content.py), so DE vs EN must genuinely differ; the honest
claim that only JPEG/WebP hit an exact target (video and PNG/TIFF are
quality-only) is present in both locales; a "PDFs?" handoff links
``/pdf/compress``; the sitemap / llms.txt / footer / /tools / /formats
surfaces all discover the page; and it stays deployment-agnostic.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from app.core.compress_content import COMPRESS_CONTENT
from app.core.tools_content import TOOLS_CONTENT


def _main(html: str) -> str:
    """Slice the page's <main> block — link/content asserts must not pass
    just because base.html's navbar/footer links the same URL."""
    return html[html.index("<main") : html.index("</main>")]


# ── renders + tool embedding + preset-mode hook ─────────────────────────────


def test_compress_page_renders_on_all_three_mounts(client):
    for prefix in ("", "/en", "/de"):
        r = client.get(f"{prefix}/compress")
        assert r.status_code == 200, f"{prefix}/compress -> {r.status_code}"
        assert "<h1" in r.text
        assert "<h3" in r.text  # visible FAQ headings (GEO)


def test_compress_page_embeds_the_real_tool_preset_to_compress_mode(client):
    for prefix in ("/en", "/de"):
        r = client.get(f"{prefix}/compress")
        assert r.status_code == 200
        assert 'id="drop-zone"' in r.text
        assert 'id="convert-btn"' in r.text
        assert 'id="target-size-input"' in r.text
        assert 'data-preset-mode="compress"' in r.text


def test_homepage_unaffected_by_preset_mode_hook(client):
    """Zero-behaviour-change guard: the shared partial renders the
    data-attribute everywhere, but only /compress fills it in."""
    r = client.get("/en/")
    assert r.status_code == 200
    assert 'data-preset-mode=""' in r.text
    assert 'data-preset-mode="compress"' not in r.text


# ── SERP + cannibalization guard ─────────────────────────────────────────────


def test_compress_page_title_and_meta_in_serp_range(client):
    for prefix in ("/en", "/de"):
        r = client.get(f"{prefix}/compress")
        assert r.status_code == 200
        title = re.search(r"<title[^>]*>([^<]+)</title>", r.text, re.IGNORECASE).group(1).strip()
        meta = (
            re.search(r'<meta\s+name="description"\s+content="([^"]+)"', r.text, re.IGNORECASE)
            .group(1)
            .strip()
        )
        assert len(title) <= 60, f"{prefix}/compress title {len(title)}: {title!r}"
        assert len(meta) <= 160, f"{prefix}/compress meta {len(meta)}: {meta!r}"
        assert len(title) >= 10 and len(meta) >= 50


def test_compress_page_title_and_meta_never_say_pdf(client):
    """Cannibalization guard (docs-internal/ia-navigation-konzept.md): the
    PDF slice of this query space is /pdf/compress, not /compress — the
    title/meta here must never mention "pdf", in either locale."""
    for prefix in ("/en", "/de"):
        r = client.get(f"{prefix}/compress")
        title = re.search(r"<title[^>]*>([^<]+)</title>", r.text, re.IGNORECASE).group(1)
        meta = re.search(
            r'<meta\s+name="description"\s+content="([^"]+)"', r.text, re.IGNORECASE
        ).group(1)
        assert "pdf" not in title.lower(), title
        assert "pdf" not in meta.lower(), meta


# ── DE/EN localisation ───────────────────────────────────────────────────────


def test_compress_page_localised():
    """Content lives as plain bilingual data (compress_content.py), not
    gettext — h1 AND hero must genuinely differ per locale."""
    en = COMPRESS_CONTENT["en"]
    de = COMPRESS_CONTENT["de"]
    assert en["h1"] != de["h1"]
    assert en["hero"] != de["hero"]


def test_compress_page_localised_rendered(client):
    en = COMPRESS_CONTENT["en"]
    de = COMPRESS_CONTENT["de"]
    en_html = client.get("/en/compress").text
    de_html = client.get("/de/compress").text
    assert en["h1"] in en_html
    assert de["h1"] in de_html
    assert en["hero"] in en_html
    assert de["hero"] in de_html


# ── honest limits + FAQ ───────────────────────────────────────────────────────


def test_compress_page_honest_limits_and_faq_render(client):
    r = client.get("/en/compress")
    assert "Honest limits" in r.text
    assert "Frequently asked questions" in r.text
    for q, _a in COMPRESS_CONTENT["en"]["faq"]:
        assert q in r.text


def test_compress_page_states_which_formats_support_target_size(client):
    """Claims-discipline guard (project motto: never overclaim). Exact
    target-size compression only works for JPEG/WebP — verified against
    TARGET_SIZE_FORMATS in app/static/js/app.js and app/compressors/video.py
    (no target_bytes parameter at all). Video and PNG/TIFF are quality-only,
    stated plainly in both locales."""
    en = client.get("/en/compress").text
    de = client.get("/de/compress").text
    # Straight apostrophes render HTML-escaped (Jinja autoescape → &#39;),
    # so the asserted substrings below stop just short of any apostrophe.
    assert "PNG, TIFF and video" in en and "take a target size" in en
    assert "no byte-exact target" in en
    assert "PNG, TIFF und Video nehmen keine Zielgröße entgegen" in de
    assert "kein exaktes Byte-Ziel" in de


# ── PDF handoff ───────────────────────────────────────────────────────────────


def test_compress_page_pdf_handoff_link_inside_main(client):
    r = client.get("/en/compress")
    main = _main(r.text)
    handoff = main[main.index("PDFs?") :][:800]
    assert 'href="/en/pdf/compress"' in handoff, (
        "the dedicated PDFs? handoff box must carry the /pdf/compress link"
    )


def test_compress_page_pdf_handoff_localised_on_de(client):
    r = client.get("/de/compress")
    main = _main(r.text)
    assert 'href="/de/pdf/compress"' in main


# ── related tools + deployment-agnostic ──────────────────────────────────────


def test_compress_page_related_tools_link_hub_and_formats(client):
    main = _main(client.get("/en/compress").text)
    assert 'href="/en/tools"' in main
    assert 'href="/en/formats"' in main


def test_compress_page_deployment_agnostic(client):
    r = client.get("/en/compress")
    assert "filemorph.io" not in r.text


# ── discovery surfaces ───────────────────────────────────────────────────────


def test_sitemap_lists_compress_page_with_hreflang(client):
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
    assert any(loc.endswith("/compress") and "/pdf/" not in loc for loc in locs), (
        "missing x-default /compress"
    )
    assert any(loc.endswith("/en/compress") for loc in locs), "missing /en/compress"
    assert any(loc.endswith("/de/compress") for loc in locs), "missing /de/compress"

    checked = 0
    for u in root.findall("sm:url", ns):
        loc = u.find("sm:loc", ns).text or ""
        if loc.endswith("/compress") and "/pdf/" not in loc:
            hreflangs = {a.attrib.get("hreflang") for a in u.findall("xhtml:link", ns)}
            assert hreflangs == {"x-default", "de", "en"}, f"{loc} hreflangs {hreflangs}"
            checked += 1
    assert checked == 3  # x-default + de + en


def test_llms_txt_lists_compress_page(client):
    llms = client.get("/llms.txt").text
    assert "[Compress an image or video]" in llms


def test_tools_hub_links_compress_target_card(client):
    """/tools gets a second card, "Compress to a target size", next to
    Convert & Compress (IA rework PR 4) — card body renders, not just the
    link, and it's scoped inside <main> so this doesn't pass merely because
    the footer links the same URL."""
    r = client.get("/en/tools")
    main = _main(r.text)
    assert 'href="/en/compress"' in main
    assert TOOLS_CONTENT["en"]["cards"]["compress_target"]["title"] in main


def test_compress_target_card_links_compress_page_both_locales(client):
    en_main = _main(client.get("/en/tools").text)
    de_main = _main(client.get("/de/tools").text)
    assert 'href="/en/compress"' in en_main
    assert 'href="/de/compress"' in de_main
    assert "target size" in TOOLS_CONTENT["en"]["cards"]["compress_target"]["desc"]
    assert "Zielgröße" in TOOLS_CONTENT["de"]["cards"]["compress_target"]["desc"]


def test_formats_page_target_size_cta_links_compress(client):
    """The "Compress to a target size" section's CTA used to link `/`; IA
    rework PR 4 repoints it at the new dedicated page."""
    main = _main(client.get("/en/formats").text)
    start = main.index("Compress to a target size")
    section = main[start : main.index('<div class="grid', start)]
    assert 'href="/en/compress"' in section
    assert 'href="/en/"' not in section


# ── footer — see also tests/test_footer_nav_structure.py::test_footer_tools_group_links ─


def test_footer_links_compress_page_localized(client):
    en = client.get("/en/").text
    de = client.get("/de/").text
    assert 'href="/en/compress"' in en
    assert 'href="/de/compress"' in de
