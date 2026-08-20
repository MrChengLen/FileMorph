# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests for the informational cookie notice.

The notice (partials/cookie_notice.html + cookie-notice.js) is deliberately
NOT a consent dialog: FileMorph sets no cookies and loads no third-party
resources, so there is nothing to consent to (§ 25 Abs. 2 Nr. 2 TDDDG /
Art. 5(3) ePrivacy). These tests pin its contract: rendered on every
base-template page but hidden until JS reveals it, dismiss button wired by
id for cookie-notice.js, a locale-aware deep link into the privacy policy's
cookie section, translated texts on both locales — and no consent controls,
ever.
"""

from __future__ import annotations

import re


def test_notice_rendered_hidden_with_dismiss_button(client):
    html = client.get("/").text
    assert 'id="cookie-notice"' in html
    assert re.search(r'id="cookie-notice"[^>]*class="[^"]*\bhidden\b', html), (
        "notice must render with the hidden class so returning visitors "
        "never see a flash before cookie-notice.js runs"
    )
    assert html.count('id="cookie-notice-dismiss"') == 1
    assert "/static/js/cookie-notice.js" in html


def test_notice_is_not_a_consent_dialog(client):
    """The bar informs — it must never grow Accept/Reject consent controls;
    there is nothing to consent to, and a fake choice would be misleading."""
    html = client.get("/").text
    assert "cookie-notice-accept" not in html
    assert "cookie-notice-reject" not in html


def test_notice_deep_links_privacy_cookies_section(client):
    assert 'href="/privacy#cookies"' in client.get("/").text
    assert 'id="cookies"' in client.get("/privacy").text


def test_notice_localized_texts_and_links(client):
    de = client.get("/de/").text
    en = client.get("/en/").text
    assert "Verstanden" in de
    assert "Got it" in en
    assert 'href="/de/privacy#cookies"' in de
    assert 'href="/en/privacy#cookies"' in en
