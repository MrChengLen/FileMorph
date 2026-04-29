# SPDX-License-Identifier: AGPL-3.0-or-later
"""Transactional email sender — thin async wrapper around ``aiosmtplib``.

Design notes
------------
* Zero side-effects when :attr:`Settings.smtp_host` is empty, so the local
  dev stack (no SMTP creds) and the test suite (which monkey-patches
  :func:`send_email` anyway) keep working.
* TLS mode is chosen by port: 465 → implicit SSL from the first byte, any
  other port (e.g. 587) → plain connect + ``STARTTLS``. Hetzner Cloud
  blocks outbound 465 for new accounts by default, so 587 is the path of
  least friction unless you've explicitly opened 465 with Hetzner support.
* Errors surface as :class:`EmailSendError` with no SMTP details so the
  caller can return a generic response without leaking infrastructure
  hints.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailSendError(RuntimeError):
    """Raised when SMTP delivery fails. The original SMTP error is logged but
    never included in the message — it may contain addresses or hostnames we
    don't want to bubble up to an HTTP response."""


async def send_email(*, to: str, subject: str, html: str, text: str) -> None:
    """Send a multipart text+html email.

    If ``settings.smtp_host`` is empty the function logs a warning and
    returns — this is the local-dev / CI path with no outbound traffic.
    """
    to_domain = to.split("@", 1)[-1] if "@" in to else "unknown"
    if not settings.smtp_host:
        logger.warning(
            "send_email skipped — SMTP not configured (to_domain=%s, subject=%r)",
            to_domain,
            subject,
        )
        return

    from_email = settings.smtp_from_email or settings.smtp_username
    if not from_email:
        raise EmailSendError("SMTP_FROM_EMAIL / SMTP_USERNAME is not configured.")

    msg = EmailMessage()
    msg["From"] = (
        f"{settings.smtp_from_name} <{from_email}>" if settings.smtp_from_name else from_email
    )
    msg["To"] = to
    msg["Subject"] = subject
    if settings.smtp_reply_to:
        msg["Reply-To"] = settings.smtp_reply_to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    tls_kwargs = {"use_tls": True} if settings.smtp_port == 465 else {"start_tls": True}

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            timeout=20,
            **tls_kwargs,
        )
        logger.info("send_email ok to_domain=%s subject=%r", to_domain, subject)
    except Exception as exc:
        logger.exception("send_email failed to_domain=%s subject=%r", to_domain, subject)
        raise EmailSendError("Failed to deliver email.") from exc
