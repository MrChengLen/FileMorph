# SPDX-License-Identifier: AGPL-3.0-or-later
"""Status page link (``STATUS_PAGE_URL``) and section 4a of the privacy policy.

Guards:
  - Off by default: a self-hosted instance links no status page it does not
    run (same reasoning as PRICING_PAGE_ENABLED).
  - Set: the footer's Product group links it, translated in both locales.
  - The privacy policy is filemorph.io's own notice, so section 4a describes
    filemorph.io's status page in both locales, independent of the switch.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, settings
from app.core.templates import templates

_URL = "https://status.example.com/"
_PRODUCT_GROUP = {"/en/": 'aria-label="Product"', "/de/": 'aria-label="Produkt"'}


def _product_group(html: str, path: str) -> str:
    """The footer's Product <nav>, so a match elsewhere on the page cannot pass."""
    footer = html[html.index("<footer") :]
    start = footer.index(_PRODUCT_GROUP[path])
    return footer[start : footer.index("</nav>", start)]


def _set_status_page(monkeypatch, url: str) -> None:
    monkeypatch.setattr(settings, "status_page_url", url)
    monkeypatch.setitem(templates.env.globals, "status_page_url", url)


def test_status_page_url_defaults_to_empty():
    assert Settings.model_fields["status_page_url"].default == ""


def test_setting_is_wired_into_the_templates(client):
    """The other tests set the Jinja global themselves; this one pins the line
    in app.main that copies the setting there (``client`` imports app.main)."""
    assert templates.env.globals["status_page_url"] == settings.status_page_url


@pytest.mark.parametrize("path", ["/en/", "/de/"])
def test_footer_has_no_status_link_when_unset(client, monkeypatch, path):
    _set_status_page(monkeypatch, "")
    html = client.get(path).text
    footer = html[html.index("<footer") :]
    assert "Status page" not in footer
    assert "Statusseite" not in footer


@pytest.mark.parametrize(("path", "label"), [("/en/", "Status page ↗"), ("/de/", "Statusseite ↗")])
def test_footer_links_the_status_page_when_set(client, monkeypatch, path, label):
    _set_status_page(monkeypatch, _URL)
    group = _product_group(client.get(path).text, path)
    assert f'<a href="{_URL}" target="_blank"' in group
    assert label in group


@pytest.mark.parametrize(
    ("path", "heading", "snippets"),
    [
        (
            "/en/privacy",
            "4a. Status page (GitHub)",
            (
                "The status page sets no cookies and uses no tracking.",
                "keeps a copy of the public status data",
                "the connection through Cloudflare, the status page (§ 4a),",
            ),
        ),
        (
            "/de/privacy",
            "4a. Statusseite (GitHub)",
            (
                "Die Statusseite setzt keine Cookies und nutzt kein Tracking.",
                "legt die Seite eine Kopie der öffentlichen Statusdaten",
                "die Verbindung über Cloudflare, die Statusseite (§ 4a),",
            ),
        ),
    ],
)
def test_privacy_policy_describes_the_status_page(client, path, heading, snippets):
    """Section 4a exists, discloses the browser storage (§ 6 counts localStorage
    like cookies) and the status page appears in the legitimate-interest list."""
    html = client.get(path).text
    section = html[html.index('id="status-page"') :]
    assert heading in section
    for snippet in snippets[:2]:
        assert snippet in section
    assert snippets[2] in html
    assert 'href="https://mrchenglen.github.io/filemorph-status/"' in section
