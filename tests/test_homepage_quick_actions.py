# SPDX-License-Identifier: AGPL-3.0-or-later
"""Homepage quick actions — Step 2 of the operations-visibility rework
(docs-internal/operations-visibility-konzept.md, section "Startseite").

Replaces tests/test_homepage_more_tools.py: the old "More tools" box is
gone, and its links now live in a 7-chip quick-actions row rendered inside
the shared partials/convert_tool.html, gated by show_quick_actions (set
only by pages.py::index so /compress and the 12 /convert/<pair> pages,
which render the same partial, don't get self-links or a diluted row).
The heading-outline guards that used to live next to the old box moved to
tests/test_homepage_outline.py.

Guards:
  - Exactly the 7 chip hrefs in spec order, locale-prefixed, plus the
    "All tools" link, inside <main> (not just anywhere on the page).
  - Labels localized: German chip text on /de/, English on /en/, no
    cross-language leakage inside the block.
  - Absent on /compress and on a pair page (/convert/jpg-to-pdf).
  - Every chip target actually resolves (HTTP 200) — no dead links.
  - Deployment-agnostic (no hardcoded filemorph.io) and <main> never links
    the gated /redact route, flag on or off (the footer may).
  - The chips belong to the idle state: app.js hides the row once files are
    chosen and shows it again when the selection is cleared.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_APP_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js"

# Chip order + targets from docs-internal/operations-visibility-konzept.md
# ("Startseite" table): (url_path, EN label, DE label).
_CHIPS = (
    ("/pdf/compress", "Compress PDF", "PDF verkleinern"),
    ("/convert/jpg-to-pdf", "JPG to PDF", "JPG in PDF"),
    ("/convert/docx-to-pdf", "Word to PDF", "Word in PDF"),
    ("/pdf/split", "Split PDF", "PDF aufteilen"),
    ("/pdf/extract", "Extract PDF pages", "PDF-Seiten extrahieren"),
    ("/convert/heic-to-jpg", "HEIC to JPG", "HEIC in JPG"),
    ("/compress", "Compress image (KB/MB)", "Bild verkleinern (KB/MB)"),
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
    expected = [f"{prefix}{path}" for path, *_ in _CHIPS] + [f"{prefix}/tools"]
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


# ── old "More tools" section is gone ──────────────────────────────────────


def test_more_tools_heading_removed_on_en(client):
    assert "More tools" not in _main(client.get("/en/").text)


def test_more_tools_heading_removed_on_de(client):
    assert "Weitere Tools" not in _main(client.get("/de/").text)


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


@pytest.mark.parametrize("path", [chip[0] for chip in _CHIPS] + ["/tools"])
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
    assert "setQuickActionsVisible(true)" in _js_function(source, "clearAllFiles")
