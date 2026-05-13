# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public ``/contact`` form endpoint.

Anonymous and stateless. A submission is emailed to the operator
(recipient resolved from ``CONTACT_FORM_RECIPIENT_EMAIL`` →
``SMTP_REPLY_TO`` → ``SMTP_FROM_EMAIL``) with ``Reply-To`` set to the
submitter so the operator can answer directly — that two-way reachability
is what lets a contact form stand in for a phone number under German
DDG §5 / ECJ C-298/07.

The message body is **never persisted**. The only record kept is an audit
event (``contact.message.received``) with a hashed email + the submitter's
browser locale — and even that is a no-op-with-warning on a deployment
without ``DATABASE_URL`` (``record_event`` opens its own session), so the
form works on the Community edition too.

Spam controls — no external captcha (the project promises "no external
resources"):

* a hidden honeypot field (``website``). A non-empty value still gets the
  normal ``200`` — but no email and no audit event — so a bot believes it
  succeeded and stops, without learning it was detected.
* a ``5/hour`` per-IP rate limit.
* a 20-character minimum on the message, plus length caps on every field.

This endpoint deliberately returns ``502`` (not the generic ``200`` that
``/forgot-password`` returns on a send failure): there is no enumeration
concern here, and the user genuinely needs to know whether the message got
through — on failure the UI hands them the direct-email fallback.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.core import email as email_mod
from app.core.audit import record_event as audit_record
from app.core.config import settings
from app.core.i18n import resolve_locale
from app.core.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Contact"])


class ContactRequest(BaseModel):
    name: str = Field("", max_length=120)
    email: EmailStr
    subject: str = Field("", max_length=160)
    message: str = Field(..., min_length=20, max_length=5000)
    # Honeypot. NOT enforced by the schema on purpose — a 422 would leak
    # the field name (the validation-error handler echoes ``loc``) and
    # tell the bot it was caught. Accepted and bounded; the endpoint
    # checks it and silently drops a non-empty value with a fake 200.
    website: str = Field("", max_length=200)


def _recipient() -> str:
    return (
        settings.contact_form_recipient_email or settings.smtp_reply_to or settings.smtp_from_email
    )


@router.post("/contact", status_code=status.HTTP_200_OK)
@limiter.limit("5/hour")
async def submit_contact(request: Request, body: ContactRequest):
    # TODO(followup, PR-R3): _client_ip / email-hashing are duplicated
    # from app/api/routes/auth.py — extract to app/core/request_helpers.py
    # when auth.py is split into a sub-package.
    actor_ip = request.client.host if request.client else None

    if body.website.strip():
        # Honeypot tripped: return the same 200 a successful send returns,
        # but do nothing — no email, no audit event.
        logger.info("contact: honeypot tripped, dropping submission (ip=%s)", actor_ip)
        return {"detail": "Message sent."}

    locale = resolve_locale(request)
    email_hash = hashlib.sha256(body.email.strip().lower().encode("utf-8")).hexdigest()
    await audit_record(
        "contact.message.received",
        actor_ip=actor_ip,
        payload={"email_hash": email_hash, "locale": locale},
    )

    subject_line = (
        f"[FileMorph Kontakt] {body.subject.strip() or 'Nachricht über das Kontaktformular'}"
    )
    name_line = body.name.strip() or "(kein Name angegeben)"
    text = (
        f"Name: {name_line}\nE-Mail: {body.email}\nSprache: {locale}\n---\n{body.message.strip()}\n"
    )
    # The operator-notification email is a plain f-string — it does NOT
    # go through an autoescaping Jinja env — so user content must be
    # escaped here. A <pre> wrapper is the lowest-surface-area way to
    # satisfy send_email's html= argument while preserving line breaks.
    html_body = (
        '<pre style="white-space:pre-wrap;font-family:inherit;margin:0">'
        + html_mod.escape(text)
        + "</pre>"
    )

    recipient = _recipient()
    try:
        await email_mod.send_email(
            to=recipient,
            subject=subject_line,
            html=html_body,
            text=text,
            reply_to=body.email,
        )
    except email_mod.EmailSendError:
        recipient_domain = recipient.split("@", 1)[-1] if "@" in recipient else "unknown"
        logger.exception("contact: delivery failed (recipient_domain=%s)", recipient_domain)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Couldn't send your message right now — please email us directly.",
        )

    return {"detail": "Message sent."}
