# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account pages, and the links to them, exist only where accounts exist.

Accounts live in the database, so a Community Edition instance (no
``DATABASE_URL``, the suite's default) has none: the auth API answers 503
there. Without accounts no page links a sign-in or sign-up form, the account
pages 404 (same gating as /pricing), and the home page's developer teaser names
the free way to an API key, the key file, instead of the sign-up form; its curl
example targets the instance itself. With accounts (``accounts_on``, as on the
hosted service) everything stays as it was.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag

_ROOT = Path(__file__).resolve().parent.parent

_ACCOUNT_PAGES = (
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/dashboard",
    "/account-deleted",
    "/cockpit",
)
_ACCOUNT_HREF = re.compile(
    r'href="(?:/de|/en)?/(?:login|register|forgot-password|reset-password|verify-email'
    r"|dashboard|account-deleted|cockpit)\b"
)
# Pages every instance serves, the 404 page included.
_PUBLIC_PAGES = (
    "/",
    "/tools",
    "/formats",
    "/compress",
    "/pdf/split",
    "/convert/jpg-to-pdf",
    "/contact",
    "/privacy",
    "/terms",
    "/impressum",
    "/security",
    "/no-such-page",
)
_KEY_GUIDE = (
    "https://github.com/MrChengLen/FileMorph/blob/main/docs/self-hosting.md#api-key-management"
)


def _url(prefix: str, page: str) -> str:
    return f"{prefix}/" if page == "/" else prefix + page


def _teaser_links(html: str) -> dict[str, Tag]:
    """The developer teaser's links on the home page, by their text."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h2", string=re.compile("For Developers|Für Entwickler"))
    assert heading is not None, "developer teaser missing"
    return {a.get_text(strip=True): a for a in heading.parent.find_all("a")}


# ── Without accounts (Community Edition) ─────────────────────────────────────


@pytest.mark.parametrize("prefix", ["", "/de", "/en"])
@pytest.mark.parametrize("page", _ACCOUNT_PAGES)
def test_account_pages_404_without_accounts(client, prefix, page):
    r = client.get(prefix + page)
    assert r.status_code == 404
    assert re.search(r"<title>[^<]*404", r.text), "not the 404 page"


@pytest.mark.parametrize("prefix", ["", "/de", "/en"])
def test_no_page_links_an_account_page_without_accounts(client, prefix):
    for page in _PUBLIC_PAGES:
        url = _url(prefix, page)
        r = client.get(url)
        # A renamed route would otherwise check the 404 page instead.
        assert r.status_code == (404 if page == "/no-such-page" else 200), url
        html = r.text
        assert not _ACCOUNT_HREF.findall(html), f"{url} links an account page"
        # auth.js fills these containers with a Sign In link; without them it draws nothing.
        assert 'id="nav-auth-desktop"' not in html
        assert 'id="nav-auth-mobile"' not in html


@pytest.mark.parametrize(
    "prefix, label",
    [("/en", "How to get an API key ↗"), ("/de", "So bekommst du einen API-Key ↗")],
)
def test_developer_teaser_names_the_key_file_without_accounts(client, prefix, label):
    links = _teaser_links(client.get(f"{prefix}/").text)
    assert "Get API Key →" not in links and "API-Key holen →" not in links
    guide = links[label]
    assert guide["href"] == _KEY_GUIDE
    assert guide["target"] == "_blank" and guide["rel"] == ["noopener"]


@pytest.mark.parametrize("base", ["https://files.example.test", "https://filemorph.io"])
def test_developer_teaser_curl_targets_this_instance(client, monkeypatch, base):
    """A key from the key file is valid only on its own instance, so the curl
    example uses APP_BASE_URL. On filemorph.io it reads exactly as before."""
    from app.core.templates import templates

    monkeypatch.setitem(templates.env.globals, "app_base_url", base)
    html = client.get("/en/").text
    assert f"curl -X POST {base}/api/v1/convert \\" in html
    if base != "https://filemorph.io":
        assert "filemorph.io/api" not in html


def test_the_key_guide_section_exists():
    """The teaser links a heading of docs/self-hosting.md by its GitHub anchor —
    renaming the heading would break that link on every Community instance."""
    guide = (_ROOT / "docs" / "self-hosting.md").read_text(encoding="utf-8")
    anchors = {
        re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
        for heading in re.findall(r"^#{1,6} (.+)$", guide, re.MULTILINE)
    }
    assert _KEY_GUIDE.split("#", 1)[1] in anchors
    assert "scripts/generate_api_key.py" in guide


def test_auth_js_draws_nothing_without_its_container():
    """base.html leaves out both auth containers where there are no accounts;
    auth.js must then return early — without the guard it would throw on the
    missing container on every page."""
    js = (_ROOT / "app" / "static" / "js" / "auth.js").read_text(encoding="utf-8")
    assert "if (!desktop) return;" in js


# ── With accounts (the hosted service): unchanged ────────────────────────────


@pytest.mark.parametrize("page", _ACCOUNT_PAGES)
def test_account_pages_render_with_accounts(client, accounts_on, page):
    assert client.get("/en" + page).status_code == 200


@pytest.mark.parametrize("prefix", ["", "/de", "/en"])
def test_sign_in_link_in_both_navigations_with_accounts(client, accounts_on, prefix):
    soup = BeautifulSoup(client.get(f"{prefix}/").text, "html.parser")
    for container in ("nav-auth-desktop", "nav-auth-mobile"):
        hrefs = [a["href"] for a in soup.find(id=container).find_all("a")]
        assert hrefs == [f"{prefix}/login"], container


@pytest.mark.parametrize(
    "prefix, label",
    [("/en", "Get API Key →"), ("/de", "API-Key holen →")],
)
def test_developer_teaser_links_sign_up_with_accounts(client, accounts_on, prefix, label):
    links = _teaser_links(client.get(f"{prefix}/").text)
    assert links[label]["href"] == f"{prefix}/register"
    assert not [a for a in links.values() if a["href"] == _KEY_GUIDE]
