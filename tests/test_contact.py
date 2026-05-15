# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the public /contact form (page render + POST endpoint).

The endpoint has no DB dependency (``record_event`` opens its own
session, and we mock it here), so these tests need only the session
``client`` fixture from ``conftest.py`` plus ``monkeypatch`` to stub
``send_email`` / ``audit_record`` at their import sites.
"""

import re
from unittest.mock import AsyncMock

import pytest

from app.core import email as email_mod


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


def test_contact_post_happy_path(client, monkeypatch):
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
    audit_payload = audit_mock.call_args.kwargs["payload"]
    assert re.fullmatch(r"[0-9a-f]{64}", audit_payload["email_hash"])
    assert "locale" in audit_payload
    # The plaintext email never appears in the audit payload.
    assert "erika@example.com" not in str(audit_payload)


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
        {"email": "a@b.com", "message": "x" * 25},  # missing nothing required... actually fine
    ],
)
def test_contact_post_minimal_valid_body_ok(client, monkeypatch, payload):
    """name/subject/website are optional — a body with just email + a
    long-enough message is accepted."""
    send_mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", send_mock)
    monkeypatch.setattr("app.api.routes.contact.audit_record", AsyncMock())
    r = client.post("/api/v1/contact", json=payload)
    assert r.status_code == 200
    send_mock.assert_awaited_once()


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


def test_contact_post_email_failure_returns_502(client, monkeypatch):
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
