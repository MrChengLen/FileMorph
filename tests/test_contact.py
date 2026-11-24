# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the public /contact form (page render + POST endpoint).

The endpoint has no DB dependency (``record_event`` opens its own
session, and we mock it here), so these tests need only the session
``client`` fixture from ``conftest.py`` plus ``monkeypatch`` to stub
``send_email`` / ``audit_record`` at their import sites.
"""

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from bs4 import BeautifulSoup

from app.core import email as email_mod

_CONTACT_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "contact.js"


# ── Page render ───────────────────────────────────────────────────────────────


def test_contact_page_renders(client):
    r = client.get("/contact")
    assert r.status_code == 200
    body = r.text
    assert 'id="contact-form"' in body
    assert 'name="email"' in body
    assert 'name="message"' in body
    # Honeypot field is present but inside a display:none container.
    assert 'name="website"' in body
    assert 'class="hidden"' in body


def test_contact_outcome_box_shows_success_and_errors_apart(client):
    """A sent message and a failed one looked alike, and the error texts did
    not show at all. The outcome is a notice box inside a live region:
    contact.js tints it ok on success and err on every failure, and each error
    code it shows has its text on the box (read with getAttribute)."""
    box = BeautifulSoup(client.get("/contact").text, "html.parser").find(id="contact-status")
    assert box["data-component"] == "notice" and "hidden" in box["class"]
    assert box.parent.get("aria-live") == "polite"
    assert box.get("data-ok")
    js = _CONTACT_JS.read_text(encoding="utf-8")
    assert "showStatus(status.dataset.ok, 'ok')" in js
    codes = set(re.findall(r"showError\((\d+)\)", js))
    assert codes, "contact.js shows no error codes — regex drift?"
    for code in sorted(codes):
        assert box.get(f"data-err-{code}"), f"data-err-{code} missing: that error would be empty"


@pytest.mark.parametrize("address", ["", "team@example.org"])
def test_contact_server_error_names_the_address_when_there_is_one(client, monkeypatch, address):
    """Never a dead end: with an operator address the server-error text says
    where to write instead; without one it stops after the apology."""
    monkeypatch.setattr(email_mod.settings, "contact_form_recipient_email", address)
    monkeypatch.setattr(email_mod.settings, "smtp_reply_to", "")
    monkeypatch.setattr(email_mod.settings, "smtp_from_email", "")
    soup = BeautifulSoup(client.get("/en/contact").text, "html.parser")
    box = soup.find(id="contact-status")
    texts = {
        "data-err-500": "Sorry, we could not send your message right now.",
        "data-err-503": "Sending messages through this form is not set up on this server.",
    }
    for attr, start in texts.items():
        text = box[attr]
        assert text.startswith(start), attr
        if address:
            assert text.endswith(f"Please email us directly at {address}."), attr
        else:
            assert "Please email us directly" not in text, attr
    # "Write an email instead": only with an address to write to, hidden until
    # an error the form cannot deliver past (contact.js fills subject and body).
    mailto = soup.find(id="contact-mailto")
    if address:
        assert mailto["href"] == f"mailto:{address}" and "hidden" in mailto["class"]
    else:
        assert mailto is None


def test_contact_js_offers_mail_only_where_the_form_cannot_deliver():
    js = _CONTACT_JS.read_text(encoding="utf-8")
    codes = re.search(r"MAILTO_CODES = \[([^\]]*)\]", js)
    assert codes and {c.strip() for c in codes.group(1).split(",")} == {"429", "500", "503"}
    # What the visitor typed goes into the link URI-encoded, never raw, subject
    # and message character by character (a cut through an emoji would throw).
    assert "encodeWithin(text, room)" in js and "encodeURIComponent(ch)" in js
    assert "encodeURIComponent(subject)" not in js


@pytest.mark.parametrize("prefix,lang", [("/de", "de"), ("/en", "en")])
def test_contact_page_localized(client, prefix, lang):
    r = client.get(f"{prefix}/contact")
    assert r.status_code == 200
    assert f'<html lang="{lang}"' in r.text


def test_impressum_links_to_contact_and_uses_ddg(client):
    """Regression guard for the DDG §5 second-contact-channel requirement:
    the Impressum must link to /contact and cite the current statute (DDG),
    not the repealed TMG."""
    r = client.get("/impressum")
    assert r.status_code == 200
    body = r.text
    assert "/contact" in body
    assert "Kontaktformular" in body
    assert "§ 5 DDG" in body
    assert "§ 5 TMG" not in body


# ── POST /api/v1/contact ──────────────────────────────────────────────────────


@pytest.fixture
def smtp_on(monkeypatch):
    """A deployment that can send mail. Without SMTP the endpoint answers 503
    (test_contact_post_without_smtp_is_503_not_a_false_success)."""
    monkeypatch.setattr(email_mod.settings, "smtp_host", "smtp.example.test")


def test_contact_post_without_smtp_is_503_not_a_false_success(client, monkeypatch):
    """send_email skips the mail when SMTP is not set up, so a 200 here told
    the visitor "sent" while nobody would ever read the message. The form
    says it is not set up instead; nothing is sent and nothing audited."""
    monkeypatch.setattr(email_mod.settings, "smtp_host", "")
    send_mock = AsyncMock()
    audit_mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", send_mock)
    monkeypatch.setattr("app.api.routes.contact.audit_record", audit_mock)
    r = client.post("/api/v1/contact", json={"email": "erika@example.com", "message": "x" * 25})
    assert r.status_code == 503
    assert "smtp" not in r.text.lower()
    send_mock.assert_not_awaited()
    audit_mock.assert_not_awaited()


def test_contact_post_happy_path(client, monkeypatch, smtp_on):
    send_mock = AsyncMock()
    audit_mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", send_mock)
    monkeypatch.setattr("app.api.routes.contact.audit_record", audit_mock)

    payload = {
        "name": "Erika Mustermann",
        "email": "erika@example.com",
        "subject": "Hello",
        "message": "x" * 25,
        "website": "",
    }
    r = client.post("/api/v1/contact", json=payload)
    assert r.status_code == 200
    assert r.json() == {"detail": "Message sent."}

    send_mock.assert_awaited_once()
    sent_kwargs = send_mock.call_args.kwargs
    assert sent_kwargs.get("reply_to") == "erika@example.com"
    assert "to" in sent_kwargs and "html" in sent_kwargs and "text" in sent_kwargs
    # The submitter's address must not be HTML-injected raw — it rides in
    # the <pre>-escaped body; the message text itself is in there.
    assert "x" * 25 in sent_kwargs["text"]

    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.args[0] == "contact.message.received"
    # The audit entry keeps the language only: nothing derived from the
    # sender's address, which would stay in the hash chain for good.
    audit_payload = audit_mock.call_args.kwargs["payload"]
    assert set(audit_payload) == {"locale"}


def test_contact_post_honeypot_silently_dropped(client, monkeypatch):
    send_mock = AsyncMock()
    audit_mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", send_mock)
    monkeypatch.setattr("app.api.routes.contact.audit_record", audit_mock)

    payload = {
        "name": "spambot",
        "email": "bot@example.com",
        "subject": "buy now",
        "message": "y" * 30,
        "website": "http://spam.example/cheap-pills",
    }
    r = client.post("/api/v1/contact", json=payload)
    # Same 200 a real send returns — the bot must not learn it was caught.
    assert r.status_code == 200
    assert r.json() == {"detail": "Message sent."}
    send_mock.assert_not_awaited()
    audit_mock.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "x" * 25},  # missing email
        {"email": "a@b.com", "message": "too short"},  # < 20 chars
        {"email": "not-an-email", "message": "x" * 25},  # invalid email
        {"email": "a@b.com"},  # missing message
    ],
)
def test_contact_post_validation_errors(client, monkeypatch, payload):
    send_mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", send_mock)
    monkeypatch.setattr("app.api.routes.contact.audit_record", AsyncMock())
    r = client.post("/api/v1/contact", json=payload)
    assert r.status_code == 422
    send_mock.assert_not_awaited()


def test_contact_post_email_failure_returns_502(client, monkeypatch, smtp_on):
    send_mock = AsyncMock(side_effect=email_mod.EmailSendError("smtp boom"))
    monkeypatch.setattr(email_mod, "send_email", send_mock)
    monkeypatch.setattr("app.api.routes.contact.audit_record", AsyncMock())

    r = client.post(
        "/api/v1/contact",
        json={"email": "erika@example.com", "message": "x" * 25},
    )
    assert r.status_code == 502
    # No SMTP detail leaks into the response.
    assert "boom" not in r.text.lower()
    assert "smtp" not in r.text.lower()
