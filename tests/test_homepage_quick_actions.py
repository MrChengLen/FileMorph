# SPDX-License-Identifier: AGPL-3.0-or-later
"""Homepage quick actions — Step 2 of the operations-visibility rework
(docs-internal/operations-visibility-konzept.md, section "Startseite").

Replaces tests/test_homepage_more_tools.py: the old "More tools" box is
gone, and its links now live in the quick actions rendered inside the
shared partials/convert_tool.html, gated by quick_action_groups (passed
only by pages.py::index so /compress and the /convert/<pair> pages, which
render the same partial, don't get self-links or a diluted row). The chips
come from the page catalogue (app/core/catalog.py), grouped by their /tools
section (at most twelve, at most six to a group); this file pins the result.
The heading-outline guards that used to live next to the old box moved to
tests/test_homepage_outline.py.

Guards:
  - Exactly the chip hrefs in group order, locale-prefixed, plus the
    "All tools" link, inside <main> (not just anywhere on the page).
  - Each group is labelled with its /tools section name, in the /tools
    order, and its list points at that label.
  - Labels localized: German chip text on /de/, English on /en/, no
    cross-language leakage inside the block.
  - Absent on /compress and on a pair page (/convert/jpg-to-pdf).
  - Every chip target actually resolves (HTTP 200) — no dead links.
  - Deployment-agnostic (no hardcoded filemorph.io) and <main> never links
    the gated /redact route, flag on or off (the footer may).
  - The chips belong to the idle state: app.js hides the row once files are
    chosen and shows it again when the selection is cleared — unless a
    "#convert=" link pre-sets the converter, which keeps them hidden.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_APP_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js"

# Chip order + targets (docs-internal/operations-visibility-konzept.md,
# "Startseite"; grouped by /tools section since 2026-10-28):
# (url_path, EN label, DE label), in the order the page shows them.
_CHIPS = (
    ("/pdf/compress", "Compress PDF", "PDF verkleinern"),
    ("/convert/jpg-to-pdf", "JPG to PDF", "JPG in PDF"),
    ("/convert/docx-to-pdf", "Word to PDF", "Word in PDF"),
    ("/pdf/split", "Split PDF", "PDF aufteilen"),
    ("/pdf/extract", "Extract PDF pages", "PDF-Seiten extrahieren"),
    ("/pdf/insert", "Insert PDF pages", "PDF-Seiten einfügen"),
    ("/convert/heic-to-jpg", "HEIC to JPG", "HEIC in JPG"),
    ("/compress", "Compress image (KB/MB)", "Bild verkleinern (KB/MB)"),
    ("/convert/video-to-gif", "Video to GIF", "Video in GIF"),
)
# The groups: (id suffix, EN label, DE label) — the /tools section names.
_GROUPS = (
    ("pdf", "PDF tools", "PDF-Tools"),
    ("image", "Images", "Bilder"),
    ("more", "More tools", "Weitere Tools"),
)


def _main(html: str) -> str:
    """Slice the page's <main> block — asserts must not pass just because
    base.html's navbar/footer links the same URL."""
    return html[html.index("<main") : html.index("</main>")]


def _quick_actions_block(html: str) -> str:
    """Slice the quick-actions <nav> itself, anchored on its (locale-
    agnostic) aria-labelledby so this works on /de/ too."""
    marker = html.index('aria-labelledby="quick-actions-label"')
    start = html.rindex("<nav", 0, marker)
    end = html.index("</nav>", start) + len("</nav>")
    return html[start:end]


def _js_function(source: str, name: str) -> str:
    """Body of a top-level ``function name(`` in app.js, up to the next one."""
    start = source.index(f"function {name}(")
    end = source.find("\nfunction ", start + 1)
    return source[start : end if end != -1 else None]


# ── chip presence, order and hrefs ───────────────────────────────────────


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_quick_actions_links_exact(client, prefix):
    block = _quick_actions_block(_main(client.get(f"{prefix}/").text))
    expected = [f"{prefix}{path}" for path, *_ in _CHIPS] + [f"{prefix}/tools", f"{prefix}/formats"]
    assert re.findall(r'href="([^"]+)"', block) == expected


# ── localized labels ─────────────────────────────────────────────────────


def test_quick_actions_labels_localized_on_en(client):
    block = _quick_actions_block(_main(client.get("/en/").text))
    assert "Or choose directly" in block
    for _path, en_label, de_label in _CHIPS:
        assert en_label in block
        assert de_label not in block
    assert "All tools →" in block


def test_quick_actions_labels_localized_on_de(client):
    block = _quick_actions_block(_main(client.get("/de/").text))
    assert "Oder direkt wählen" in block
    for _path, en_label, de_label in _CHIPS:
        assert de_label in block
        assert en_label not in block
    assert "Alle Tools →" in block


# ── absent on the shared partial's other pages ────────────────────────────


def test_quick_actions_absent_on_compress_page(client):
    assert 'aria-labelledby="quick-actions-label"' not in client.get("/en/compress").text


def test_quick_actions_absent_on_pair_page(client):
    html = client.get("/en/convert/jpg-to-pdf").text
    assert 'aria-labelledby="quick-actions-label"' not in html


# ── groups: the /tools section names, in the /tools order ─────────────────


@pytest.mark.parametrize(("prefix", "column"), [("/en", 1), ("/de", 2)])
def test_quick_action_groups_are_labelled(client, prefix, column):
    block = _quick_actions_block(_main(client.get(f"{prefix}/").text))
    labels = re.findall(r'<p id="quick-actions-([a-z]+)"[^>]*>([^<]+)</p>', block)
    assert labels == [(group[0], group[column]) for group in _GROUPS]
    for suffix, *_ in _GROUPS:
        assert f'<ul aria-labelledby="quick-actions-{suffix}"' in block


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_quick_action_groups_follow_the_tools_sections(client, prefix):
    """A tool sits under the same name on the homepage as on /tools."""
    block = _quick_actions_block(_main(client.get(f"{prefix}/").text))
    groups = re.findall(r'<p id="quick-actions-[a-z]+"[^>]*>([^<]+)</p>', block)
    tools = client.get(f"{prefix}/tools").text
    for family in re.findall(r'<p id="quick-actions-([a-z]+)"', block):
        section = re.search(rf'<section id="{family}".*?</section>', tools, re.S).group(0)
        group = re.search(rf'<ul aria-labelledby="quick-actions-{family}".*?</ul>', block, re.S)
        hrefs = re.findall(r'href="([^"]+)"', group.group(0))
        assert hrefs and all(f'href="{href}"' in section for href in hrefs), family
    sections = re.findall(r'<h2 class="text-base font-semibold text-white">([^<]+)</h2>', tools)
    assert groups == [name for name in sections if name in groups]


@pytest.mark.parametrize("redact", [False, True], ids=["redact-off", "redact-on"])
def test_at_most_six_quick_actions_to_a_group(request, redact):
    """Two rows of three on a wide screen; more would make a third."""
    from app.core import catalog

    if redact:
        request.getfixturevalue("redact_enabled")
    assert all(len(chips) <= 6 for _family, chips in catalog.quick_action_sections())


# ── old "More tools" box is gone; the words only name a group ─────────────


@pytest.mark.parametrize(("prefix", "words"), [("/en", "More tools"), ("/de", "Weitere Tools")])
def test_more_tools_is_no_heading_on_the_homepage(client, prefix, words):
    main = _main(client.get(f"{prefix}/").text)
    assert not re.search(rf"<h[1-6][^>]*>\s*{words}", main)
    assert main.count(words) == _quick_actions_block(main).count(words) == 1


# ── Redact never an idle homepage link, flag on or off ────────────────────


def test_homepage_main_never_links_redact_flag_off(client):
    assert "/redact" not in _main(client.get("/en/").text)


def test_homepage_main_never_links_redact_flag_on(client, redact_enabled):
    assert "/redact" not in _main(client.get("/en/").text)


# ── deployment-agnostic ───────────────────────────────────────────────────


def test_quick_actions_deployment_agnostic(client):
    block = _quick_actions_block(_main(client.get("/en/").text))
    assert "filemorph.io" not in block


# ── every chip target resolves ─────────────────────────────────────────────


@pytest.mark.parametrize("path", [chip[0] for chip in _CHIPS] + ["/tools", "/formats"])
def test_quick_actions_targets_return_200(client, path):
    assert client.get(f"/en{path}").status_code == 200


# ── idle-state only: hidden while files are selected ──────────────────────


def test_quick_actions_nav_has_the_id_app_js_toggles(client):
    block = _quick_actions_block(_main(client.get("/en/").text))
    assert 'id="quick-actions"' in block


def test_app_js_hides_quick_actions_once_files_are_chosen():
    source = _APP_JS.read_text(encoding="utf-8")
    assert "getElementById('quick-actions')" in source
    assert "setQuickActionsVisible(false)" in _js_function(source, "setFiles")
    assert "setQuickActionsVisible(!hashPresetActive)" in _js_function(source, "clearAllFiles")


# ── the macros the chips use ───────────────────────────────────────────────


def test_every_tools_section_has_its_own_name():
    """A new family missing from partials/tool_sections.html would render
    without a name instead of passing as a second "More tools"."""
    from app.core import catalog
    from app.core.templates import templates

    macros = templates.env.get_template("partials/tool_sections.html").make_module(
        {"_": lambda s: s, "gettext": lambda s: s}
    )
    names = [str(macros.section_name(key)).strip() for key in (*catalog.FAMILIES, "more")]
    assert all(names) and len(set(names)) == len(names)


def test_every_icon_is_drawn():
    from app.core import catalog
    from app.core.templates import templates

    icons = templates.env.get_template("_components/icon.html").module
    assert all("<path" in str(icons.icon(name)) for name in catalog.ICONS)
