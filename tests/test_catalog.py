# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards for the page catalogue (``app/core/catalog.py``).

The catalogue is the one list of public pages; the sitemap, ``/llms.txt``,
the page routes' whitelist and the related links are views of it. These tests
keep the list and the site from drifting apart again:

- every catalogued page renders in every locale with exactly one ``<h1>``,
  and a gated page follows its own switch, not another one;
- every public page route is catalogued (or deliberately left out), and the
  content modules hold exactly the catalogued convert and PDF-tool pages;
- the sitemap and ``/llms.txt`` list exactly the catalogue, with the
  switches off and on, and every sitemap URL renders;
- no internal link on a catalogued page leads to an error page;
- every page's title and meta description fit the search-result snippet,
  and every tool page shows at least three FAQ questions;
- the ranking texts of the homepage, /tools and the tool pages (title,
  meta description, H1 to H3)
  change only on purpose. ``tests/golden/page_texts.json`` holds them; after
  a deliberate change, rerun this file with ``FILEMORPH_UPDATE_GOLDEN=1``
  (PowerShell: ``$env:FILEMORPH_UPDATE_GOLDEN = "1"``) and commit the file.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.api.routes import pages as page_routes
from app.core import catalog
from app.core.config import settings
from app.core.convert_pairs import PAIR_CONTENT
from app.core.i18n import _PATH_ALIASES_REVERSE
from app.core.pdf_tools_content import PDF_TOOL_CONTENT
from app.core.templates import templates

_GOLDEN = Path(__file__).parent / "golden" / "page_texts.json"
# The pages whose texts rank: /formats is left out because its headings list
# the converter registry and change with every new format.
_GOLDEN_KINDS = {"home", "hub", "tool", "convert"}

# Page routes that are public but deliberately listed nowhere.
_NOT_LISTED = {
    "/imprint",  # the English spelling of /impressum: the same page
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/dashboard",
    "/account-deleted",
    "/cockpit",
    "/cancel",  # § 312k BGB entry point, not landing content
}

_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)
_META_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.IGNORECASE)
_HEADING_RE = re.compile(r"<(h[1-3])\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_MD_LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")
_HREF_RE = re.compile(r'<a\s[^>]*?href="(/[^"#?]*)')


@pytest.fixture
def pricing_on(monkeypatch):
    # Both surfaces: the route reads settings per request, the templates read
    # the Jinja global set once at import.
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setitem(templates.env.globals, "pricing_enabled", True)


@pytest.fixture
def pricing_off(monkeypatch):
    monkeypatch.setattr(settings, "pricing_page_enabled", False)
    monkeypatch.setitem(templates.env.globals, "pricing_enabled", False)


@pytest.fixture
def redact_off(monkeypatch):
    monkeypatch.setattr(settings, "ai_operations_enabled", False)
    monkeypatch.setitem(templates.env.globals, "ai_operations_enabled", False)


@pytest.fixture
def stripe_off(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", False)


@pytest.fixture(params=["off", "on"])
def switches(request):
    """Every gate off (a Community self-host), then every gate on."""
    if request.param == "on":
        request.getfixturevalue("pricing_on")
        request.getfixturevalue("redact_enabled")
    else:
        request.getfixturevalue("pricing_off")
        request.getfixturevalue("redact_off")
    return request.param


@pytest.fixture(params=["community", "cloud", "all"])
def edition(request):
    """A Community self-host (every switch off); a Cloud-Edition instance with
    commercial pages, redaction and accounts on but no bookable plan; then
    every gated page open, a bookable plan included (/cancel)."""
    if request.param == "all":
        request.getfixturevalue("every_page_on")
    elif request.param == "cloud":
        request.getfixturevalue("stripe_off")
        request.getfixturevalue("pricing_on")
        request.getfixturevalue("redact_enabled")
        request.getfixturevalue("accounts_on")
    else:
        request.getfixturevalue("stripe_off")
        request.getfixturevalue("pricing_off")
        request.getfixturevalue("redact_off")
    return request.param


def _urls(page: catalog.Page) -> list[str]:
    """The page's URLs: x-default, then /de and /en where it is localized."""
    if not page.localized:
        return [page.path]
    tail = "" if page.path == "/" else page.path
    return [page.path, f"/de{tail or '/'}", f"/en{tail or '/'}"]


def _base_path(url: str) -> str:
    """A URL's catalogue path: without host, locale prefix or locale alias."""
    path = re.sub(r"^/(de|en)(?=/|$)", "", urlsplit(url).path) or "/"
    return _PATH_ALIASES_REVERSE.get(path, path)


def _ids(page: catalog.Page) -> str:
    return page.path


# ── every page renders; gated pages vanish ─────────────────────────────────


@pytest.mark.parametrize("page", catalog.PAGES, ids=_ids)
def test_every_page_renders_with_one_h1(client, pricing_on, redact_enabled, page):
    for url in _urls(page):
        r = client.get(url)
        assert r.status_code == 200, f"{url} returned {r.status_code}"
        if page.kind != "api":  # the API explorer is Swagger UI's own page
            assert r.text.count("<h1") == 1, f"{url} has {r.text.count('<h1')} <h1> elements"


@pytest.mark.parametrize("page", [p for p in catalog.PAGES if p.gate], ids=_ids)
def test_gated_page_follows_its_own_switch(client, monkeypatch, page):
    # Every other switch on: a page wired to the wrong switch still renders
    # here. (The route reads ``settings``; monkeypatch only, so teardown
    # restores each switch exactly.)
    for gate in {p.gate for p in catalog.PAGES if p.gate}:
        monkeypatch.setattr(settings, gate, gate != page.gate)
    for url in _urls(page):
        assert client.get(url).status_code == 404, f"{url} renders with {page.gate} off"


# ── routes and content modules match the catalogue ─────────────────────────


def test_every_public_page_route_is_catalogued():
    routed = set()
    for router in (page_routes.router, page_routes.docs_router):
        for route in router.routes:
            if "GET" in getattr(route, "methods", ()) and "{" not in route.path:
                routed.add(route.path)
    catalogued = {page.path for page in catalog.PAGES}
    assert _NOT_LISTED <= routed, f"stale _NOT_LISTED entries: {sorted(_NOT_LISTED - routed)}"
    missing = sorted(routed - catalogued - _NOT_LISTED)
    assert not missing, (
        f"public page routes missing from app/core/catalog.py: {missing} — add each "
        "there, or to _NOT_LISTED here with the reason it is listed nowhere"
    )
    # /convert/{pair_slug} and /pdf/{tool} serve the parametrised entries.
    unrouted = sorted(
        path for path in catalogued - routed if not path.startswith(("/convert/", "/pdf/"))
    )
    assert not unrouted, f"catalogued pages without a route: {unrouted}"


def test_content_modules_hold_exactly_the_catalogued_pages():
    convert_pages = {page.path for page in catalog.PAGES if page.kind == "convert"}
    assert convert_pages == {f"/convert/{s}-to-{t}" for s, t in PAIR_CONTENT}, (
        "a pair page needs both its PAIR_CONTENT entry and its entry in app/core/catalog.py"
    )
    pdf_tool_pages = {page.path for page in catalog.PAGES if page.path.startswith("/pdf/")}
    assert pdf_tool_pages == {f"/pdf/{tool}" for tool in PDF_TOOL_CONTENT}, (
        "a PDF tool page needs both its PDF_TOOL_CONTENT entry and its entry in app/core/catalog.py"
    )


# ── the sitemap and llms.txt are the catalogue ─────────────────────────────


def test_sitemap_lists_exactly_the_catalogue(client, switches):
    locs = _LOC_RE.findall(client.get("/sitemap.xml").text)
    listed = Counter(_base_path(url) for url in locs)
    assert set(listed) == {page.path for page in catalog.pages() if page.priority}
    assert set(listed.values()) == {3}, "each page needs its x-default, /de and /en URL"
    # Every listed URL renders: catches a priority on a page without /de and
    # /en, or a page whose real switch the catalogue doesn't name.
    dead = [url for url in locs if client.get(urlsplit(url).path).status_code != 200]
    assert not dead, f"sitemap URLs that do not render: {dead}"


def test_llms_txt_lists_exactly_the_catalogue(client, switches):
    # The "About" section links the privacy policy; only the page lists count.
    lists = client.get("/llms.txt").text.split("\n## About\n", 1)[0]
    linked = {_base_path(url) for url in _MD_LINK_RE.findall(lists)}
    assert linked == {page.path for page in catalog.pages() if page.llms or page.kind == "convert"}


# ── no dead internal link ──────────────────────────────────────────────────


def test_internal_links_lead_to_pages(client, edition):
    hrefs = set()
    for page in catalog.pages():
        for url in _urls(page):
            hrefs.update(
                href
                for href in _HREF_RE.findall(client.get(url).text)
                if not href.startswith("/static/")
            )
    broken = {href: client.get(href).status_code for href in sorted(hrefs)}
    broken = {href: status for href, status in broken.items() if status != 200}
    assert not broken, f"internal links that lead nowhere: {broken}"


# ── titles and meta descriptions fit the search snippet ────────────────────


@pytest.mark.parametrize("page", [p for p in catalog.PAGES if p.localized], ids=_ids)
def test_title_and_meta_fit_the_search_snippet(client, pricing_on, redact_enabled, page):
    # Google cuts a title at about 60 characters and a description at about 160.
    for url in _urls(page)[1:]:
        html = client.get(url).text
        title = unescape(_TITLE_RE.search(html).group(1)).strip()
        meta = unescape(_META_RE.search(html).group(1)).strip()
        assert 10 <= len(title) <= 60, f"{url} title has {len(title)} characters: {title!r}"
        assert 50 <= len(meta) <= 160, f"{url} meta has {len(meta)} characters: {meta!r}"
        if page.kind in ("tool", "convert"):
            # Real questions as visible headings: what search and answer
            # engines pick up (GEO).
            assert html.count("<h3") >= 3, f"{url} shows fewer than 3 FAQ questions"


# ── ranking texts change only on purpose ───────────────────────────────────


def _clean(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _ranking_texts(html: str) -> dict:
    return {
        "title": _clean(_TITLE_RE.search(html).group(1)),
        "meta": _clean(_META_RE.search(html).group(1)),
        "headings": [f"{tag.lower()}: {_clean(inner)}" for tag, inner in _HEADING_RE.findall(html)],
    }


def test_ranking_texts_change_only_on_purpose(client, pricing_on, redact_off, stripe_off):
    current = {}
    for page in catalog.pages():
        if page.kind in _GOLDEN_KINDS:
            for url in _urls(page)[1:]:
                current[url] = _ranking_texts(client.get(url).text)
    if os.environ.get("FILEMORPH_UPDATE_GOLDEN") == "1":
        _GOLDEN.parent.mkdir(exist_ok=True)
        _GOLDEN.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        # Fail on purpose: a session-wide switch would otherwise rewrite the
        # file on every later run, unseen.
        pytest.fail(
            "tests/golden/page_texts.json rewritten: review the diff, unset "
            "FILEMORPH_UPDATE_GOLDEN and rerun"
        )
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    changed = sorted(
        url for url in current.keys() | golden.keys() if current.get(url) != golden.get(url)
    )
    assert not changed, (
        f"title, meta description or headings changed on {changed}. Titles, H1 and FAQ "
        "questions rank in search: if the change is deliberate, rerun with "
        "FILEMORPH_UPDATE_GOLDEN=1 and commit tests/golden/page_texts.json."
    )
