# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tool pages share one layout (``templates/layouts/tool_page.html``).

Every tool and convert page of the page catalogue shows where it sits
("Tools › <its name>") instead of the old per-type "← Back" links, and ends
with the same related block: its curated neighbours, "All tools →" and the
same task via the API. The ranking texts staying unchanged through the layout
switch is pinned by ``tests/golden/page_texts.json`` (tests/test_catalog.py).
"""

from __future__ import annotations

import re

import pytest
from markupsafe import escape

from app.api.routes.pages import _related
from app.core import catalog
from app.core.config import settings
from app.core.convert_pairs import related_pairs

_TOOL_PAGES = [p for p in catalog.PAGES if p.kind in ("tool", "convert")]


def _main(html: str) -> str:
    return html[html.index("<main") : html.index("</main>")]


def _neighbours(page) -> list[str]:
    # A convert page's neighbours come from its pair family, a tool's from its
    # catalogue entry.
    if page.kind == "convert":
        return [f"/convert/{s}-to-{t}" for s, t in related_pairs(*catalog.pair_of(page.path))]
    return list(page.related)


@pytest.mark.parametrize("page", _TOOL_PAGES, ids=lambda p: p.path)
@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_tool_page_shows_its_breadcrumb(client, redact_enabled, prefix, page):
    main = _main(client.get(f"{prefix}{page.path}").text)
    crumb = main[main.index("<nav") : main.index("</nav>")]
    assert f'href="{prefix}/tools"' in crumb
    current = re.search(r'aria-current="page"[^>]*>([^<]*)<', crumb)
    assert current and current.group(1).strip() == page.label[prefix.strip("/")]


@pytest.mark.parametrize("page", _TOOL_PAGES, ids=lambda p: p.path)
def test_tool_page_has_no_back_link(client, redact_enabled, page):
    main = _main(client.get(f"/en{page.path}").text)
    assert "← Back to Convert" not in main
    assert "← All formats" not in main


@pytest.mark.parametrize(
    "page", [p for p in _TOOL_PAGES if p.path != "/redact"], ids=lambda p: p.path
)
def test_tool_page_related_block_leads_up_and_to_the_api(client, page):
    main = _main(client.get(f"/en{page.path}").text)
    related = main[main.rindex("<h2") :]
    assert 'href="/en/tools"' in related
    assert 'href="/docs"' in related
    neighbours = _neighbours(page)
    assert neighbours, f"{page.path} has no related tools"
    for path in neighbours:
        assert f'href="/en{path}"' in related, f"{page.path} misses its related {path}"
        assert f">{escape(catalog.get(path).label['en'])}</a>" in related


def test_related_links_skip_a_switched_off_page(monkeypatch):
    # G5: a related link never points at a page this deployment doesn't serve.
    monkeypatch.setitem(settings.__dict__, "ai_operations_enabled", False)
    assert _related(["/redact", "/pdf/split"], "en") == [
        {"label": "Split PDF", "path": "/pdf/split"}
    ]
