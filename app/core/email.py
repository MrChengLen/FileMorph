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

import functools
import logging
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings
from app.core.i18n import N_, normalize_locale, translator_for

logger = logging.getLogger(__name__)


# ── Localised template rendering ──────────────────────────────────────────────
#
# Email is rendered outside any HTTP request, so it can't reuse the
# request-bound translator from ``app.core.i18n.localized_context``. Each
# supported locale gets its own Jinja ``Environment`` with the matching
# ``.mo`` installed once at construction — after that the env is immutable
# and safe to reuse across concurrent sends. Templates use ``{% trans %}``
# blocks (which the ``jinja2.ext.i18n`` extension wires to that env's
# gettext) so a sentence with an interpolated value stays one translatable
# unit regardless of word order.
#
# ``autoescape=select_autoescape(["html"])`` escapes ``{{ user_email }}``
# in the ``.html`` body but leaves the ``.txt`` body verbatim.

_EMAIL_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"

# Subject lines never pass through a Jinja template, so ``N_(...)`` marks
# them for extraction; :func:`render_email` translates them per-locale.
EMAIL_SUBJECTS: dict[str, str] = {
    "verify_email": N_("Confirm your FileMorph email"),
    "password_reset": N_("Reset your FileMorph password"),
    "account_deleted": N_("Your FileMorph account has been deleted"),
    "dunning": N_("Action needed: your FileMorph payment failed"),
}


@functools.lru_cache(maxsize=None)
def _email_env(locale: str) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_EMAIL_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        extensions=["jinja2.ext.i18n"],
        enable_async=False,
    )
    env.install_gettext_translations(translator_for(locale), newstyle=True)
    # `install_gettext_translations` registers `gettext`/`ngettext` but not
    # the `_` alias the web templates use — add it so email templates can
    # write `{{ _('...') }}` the same way.
    env.globals["_"] = env.globals["gettext"]
    return env


def render_email(template_stem: str, *, locale: str | None, **context) -> tuple[str, str, str]:
    """Render an email's ``(subject, html, text)`` in the given locale.

    ``template_stem`` is the basename shared by ``<stem>.html`` and
    ``<stem>.txt`` under ``app/templates/emails/``. ``locale`` is
    normalised (an unknown value falls back to ``settings.lang_default``).
    ``locale`` is also injected into the template context so the ``.html``
    body can set ``<html lang="{{ locale }}">``.
    """
    if template_stem not in EMAIL_SUBJECTS:
        raise KeyError(
            f"no subject registered for email template {template_stem!r} — "
            f"add it to app.core.email.EMAIL_SUBJECTS"
        )
    loc = normalize_locale(locale)
    env = _email_env(loc)
    ctx = {"locale": loc, **context}
    html = env.get_template(f"{template_stem}.html").render(**ctx)
    text = env.get_template(f"{template_stem}.txt").render(**ctx)
    subject = translator_for(loc).gettext(EMAIL_SUBJECTS[template_stem])
    return subject, html, text


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
