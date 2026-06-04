# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page-render routes (HTML), mounted three times in main.py:

- at ``/`` — the unprefixed default routes (``x-default`` for SEO,
  serves the operator-default locale)
- at ``/de`` — German-locale URLs
- at ``/en`` — English-locale URLs

Each route reads ``request.state.locale`` (set by ``LocaleMiddleware``)
and renders the same template — the per-request translator in the
context decides whether the user sees DE or EN copy.

The pricing-gated pages (``/pricing``, ``/enterprise``) honour
``settings.pricing_page_enabled`` and 404 on self-host deployments
that don't run the commercial offer.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core import pricing as pricing_mod
from app.core.config import settings
from app.core.i18n import localized_context
from app.core.templates import templates

router = APIRouter(include_in_schema=False)


def _render(request: Request, name: str, **extra):
    return templates.TemplateResponse(request, name, context=localized_context(request, **extra))


@router.get("/")
async def index(request: Request):
    # The homepage tier teaser mirrors /pricing's display contract (limits
    # from quotas.py, price strings from PRICE_*_DISPLAY env) so the two
    # surfaces can't drift — see app/core/pricing.py for the centralised
    # source. On self-host deployments the teaser is wrapped in
    # ``{% if pricing_enabled %}`` and these values stay unused; passing
    # them unconditionally keeps the template free of route-coupled
    # conditionals.
    locale = getattr(request.state, "locale", settings.lang_default)
    return _render(
        request,
        "index.html",
        anon_plan=pricing_mod.anonymous_plan(locale),
        plans={p.tier: p for p in pricing_mod.saas_plans(locale)},
        saas_prices_configured=pricing_mod.saas_prices_configured(),
        price_currency=pricing_mod.price_currency(),
    )


@router.get("/impressum")
@router.get("/imprint")  # EN-locale URL alias; same handler, same template
async def impressum(request: Request):
    return _render(request, "impressum.html")


@router.get("/privacy")
async def privacy(request: Request):
    return _render(request, "privacy.html")


@router.get("/terms")
async def terms(request: Request):
    return _render(request, "terms.html")


@router.get("/security")
async def security_page(request: Request):
    # Human-readable companion to /.well-known/security.txt. The
    # security.txt Policy field points here, so this page must always
    # render — even on a self-host deployment that hasn't customised the
    # contact alias (in that case it falls back to the upstream default
    # security@filemorph.io, which is at least reachable rather than dead).
    return _render(request, "security.html")


@router.get("/contact")
async def contact_page(request: Request):
    # Ungated — the Impressum links here (DDG §5 second contact channel),
    # and the form is useful for self-hosters who set
    # CONTACT_FORM_RECIPIENT_EMAIL. When nothing is configured,
    # ``contact_email`` is "" and the template hides the "email us
    # directly" line; the form still renders (the POST then no-ops the
    # email, same as /forgot-password without SMTP).
    contact_email = (
        settings.contact_form_recipient_email
        or settings.smtp_reply_to
        or settings.smtp_from_email
        or ""
    )
    return _render(request, "contact.html", contact_email=contact_email)


@router.get("/login")
async def login_page(request: Request):
    return _render(request, "login.html")


@router.get("/register")
async def register_page(request: Request):
    return _render(request, "register.html")


@router.get("/forgot-password")
async def forgot_password_page(request: Request):
    return _render(request, "forgot-password.html")


@router.get("/reset-password")
async def reset_password_page(request: Request):
    return _render(request, "reset-password.html")


@router.get("/verify-email")
async def verify_email_page(request: Request):
    # NEU-B.3 (slice b): the email link points here. The page-level JS
    # extracts the ?token= parameter and POSTs it to
    # /api/v1/auth/verify-email so the user sees confirmation in-app.
    return _render(request, "verify-email.html")


@router.get("/dashboard")
async def dashboard_page(request: Request):
    return _render(request, "dashboard.html")


@router.get("/account-deleted")
async def account_deleted_page(request: Request):
    # Post-deletion landing page (PR-D): the dashboard "Delete account"
    # flow redirects here after a 204. Not in the nav, not in the sitemap
    # — there is nothing here to crawl.
    return _render(request, "account_deleted.html")


@router.get("/pricing")
async def pricing_page(request: Request):
    # Self-host default: no commercial pricing surface at all.
    if not settings.pricing_page_enabled:
        return templates.TemplateResponse(
            request, "404.html", context=localized_context(request), status_code=404
        )
    locale = getattr(request.state, "locale", settings.lang_default)
    return _render(
        request,
        "pricing.html",
        anon_plan=pricing_mod.anonymous_plan(locale),
        plans={p.tier: p for p in pricing_mod.saas_plans(locale)},
        compliance_plans=pricing_mod.compliance_plans(locale),
        saas_prices_configured=pricing_mod.saas_prices_configured(),
    )


@router.get("/enterprise")
async def enterprise_page(request: Request):
    # Same gating as /pricing — the Compliance-Edition landing page is part
    # of the commercial-offer surface and a self-host deployment shouldn't
    # advertise the upstream enterprise@filemorph.io contact as if it were
    # their own. Operators forking the commercial offer rewrite both pages.
    if not settings.pricing_page_enabled:
        return templates.TemplateResponse(
            request, "404.html", context=localized_context(request), status_code=404
        )
    locale = getattr(request.state, "locale", settings.lang_default)
    return _render(
        request,
        "enterprise.html",
        compliance_plans=pricing_mod.compliance_plans(locale),
    )


@router.get("/cockpit")
async def cockpit_page(request: Request):
    return _render(request, "cockpit.html")
