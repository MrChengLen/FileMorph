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
that don't run the commercial offer. The account pages (``/login``,
``/register``, ``/dashboard`` …) 404 where the instance has no accounts.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.routes.pdf_pages import INSERT_FORMATS
from app.compressors.image import _SUPPORTED_FORMATS as IMAGE_COMPRESS_FMTS
from app.compressors.video import _SUPPORTED_FORMATS as VIDEO_COMPRESS_FMTS
from app.converters.registry import get_public_conversions, get_supported_conversions
from app.core import catalog
from app.core import email as email_mod
from app.core import pricing as pricing_mod
from app.core.compress_content import get_compress_content
from app.core.config import settings
from app.core.convert_pairs import (
    accept_attr,
    get_pair_content,
    related_pairs,
)
from app.core.i18n import localized_context, normalize_locale
from app.core.pdf_tools_content import get_pdf_tool_content
from app.core.redact_content import get_redact_content
from app.core.templates import templates
from app.core.tools_content import get_tools_content
from app.core.video_gif_content import get_video_gif_content
from app.db.base import accounts_enabled

router = APIRouter(include_in_schema=False)
# /docs (the English-only API explorer) lives on its own router, which
# app/main.py mounts once at the root — not under /de and /en like `router`.
docs_router = APIRouter(include_in_schema=False)


def _render(request: Request, name: str, **extra):
    return templates.TemplateResponse(request, name, context=localized_context(request, **extra))


def _render_account_page(request: Request, name: str):
    # Accounts live in the database. Without one (Community Edition) nothing
    # on these pages can work: the auth API answers 503, and the
    # forgot-password form even reports an email it never sent. So the pages
    # 404 there, same gating shape as /pricing; the navigation and the
    # developer teaser link none of them.
    if not accounts_enabled():
        return templates.TemplateResponse(
            request, "404.html", context=localized_context(request), status_code=404
        )
    return _render(request, name)


# /formats hub — bucket the live @register registry by source-format category
# for display. The page renders whatever the registry actually returns (always
# accurate), so this map is presentation-only: anything unmapped lands in the
# "other" bucket rather than vanishing from the page.
_FORMAT_CATEGORY: dict[str, str] = {}
for _fmt in (
    "heic",
    "heif",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "avif",
    "bmp",
    "tiff",
    "tif",
    "gif",
    "ico",
):
    _FORMAT_CATEGORY[_fmt] = "image"
for _fmt in ("docx", "txt", "pdf", "md", "markdown", "html", "htm", "eml", "rtf", "odt", "pdfa"):
    _FORMAT_CATEGORY[_fmt] = "document"
for _fmt in ("xlsx", "xls", "csv", "json", "ods"):
    _FORMAT_CATEGORY[_fmt] = "spreadsheet"
for _fmt in ("mp3", "wav", "flac", "ogg", "m4a", "aac", "wma", "opus"):
    _FORMAT_CATEGORY[_fmt] = "audio"
for _fmt in ("mp4", "avi", "mov", "mkv", "webm", "flv", "wmv"):
    _FORMAT_CATEGORY[_fmt] = "video"

# Display order of the category buckets on /formats.
_CATEGORY_ORDER: tuple[str, ...] = (
    "image",
    "document",
    "spreadsheet",
    "audio",
    "video",
    "other",
)


def _related(paths, locale: str) -> list[dict]:
    """``[{label, path}]`` for the catalogue pages at ``paths`` this deployment
    serves, under their catalogue names (a switched-off page drops out, G5)."""
    links = []
    for path in paths:
        page = catalog.get(path)
        if page is not None:
            links.append({"label": page.label[locale], "path": path})
    return links


def _tool_sections(locale: str) -> list[tuple[str, list[dict]]]:
    """The /tools catalogue: ``[(family, [card, ...]), ...]`` in the sections of
    ``catalog.sections()``.

    A card's text is the tool's ``blurb``; a convert page reuses the hero line
    of its own page, so /tools makes no claim the page itself doesn't.
    """

    def card(page: catalog.Page) -> dict:
        if page.blurb:
            desc = page.blurb[locale]
        else:
            desc = get_pair_content(*catalog.pair_of(page.path), locale)["hero"]
        return {"path": page.path, "title": page.label[locale], "desc": desc}

    return [(family, [card(page) for page in tools]) for family, tools in catalog.sections()]


def _grouped_conversions() -> list[tuple[str, list[tuple[str, list[str]]]]]:
    """Group the live registry by source-format category for the template.

    Shape: ``[(category_key, [(src, [tgts]), ...]), ...]`` in
    ``_CATEGORY_ORDER`` with empty categories dropped. Sorted so the page is
    deterministic (review-friendly, stable for the render-snapshot test).

    Uses ``get_public_conversions()`` (identity pairs like ``pdf -> pdf``
    dropped) — this is a user-facing listing, and a same-format "conversion"
    would be a silent no-op re-save. ``convert_pair_page`` below still
    validates against the raw ``get_supported_conversions()`` registry.
    """
    conversions = get_public_conversions()
    buckets: dict[str, list[tuple[str, list[str]]]] = {c: [] for c in _CATEGORY_ORDER}
    for src in sorted(conversions):
        cat = _FORMAT_CATEGORY.get(src, "other")
        buckets[cat].append((src, sorted(conversions[src])))
    return [(cat, buckets[cat]) for cat in _CATEGORY_ORDER if buckets[cat]]


def _pair_pages() -> dict[tuple[str, str], str]:
    """``{(src, tgt): path}`` for the conversions with a page of their own:
    the catalogue's pair pages, and /convert/video-to-gif for every video
    format the registry turns into a GIF."""
    pages = {catalog.pair_of(page.path): page.path for page in catalog.pages(kind="convert")}
    gif_page = catalog.get("/convert/video-to-gif")
    if gif_page is not None:
        for src, targets in get_public_conversions().items():
            if "gif" in targets and _FORMAT_CATEGORY.get(src) == "video":
                pages[(src, "gif")] = gif_page.path
    return pages


@router.get("/")
async def index(request: Request):
    # The homepage tier teaser mirrors /pricing's display contract (limits
    # from quotas.py, price strings from PRICE_*_DISPLAY env) so the two
    # surfaces can't drift — see app/core/pricing.py for the centralised
    # source. On self-host deployments the teaser is wrapped in
    # ``{% if pricing_enabled %}`` and these values stay unused; passing
    # them unconditionally keeps the template free of route-coupled
    # conditionals.
    locale = normalize_locale(getattr(request.state, "locale", settings.lang_default))
    return _render(
        request,
        "index.html",
        anon_plan=pricing_mod.anonymous_plan(locale),
        plans={p.tier: p for p in pricing_mod.saas_plans(locale)},
        saas_prices_configured=pricing_mod.saas_prices_configured(),
        price_currency=pricing_mod.price_currency(),
        # Homepage-only quick actions inside the shared convert_tool.html
        # partial (docs-internal/operations-visibility-konzept.md) — no other
        # route sets this. They come from the page catalogue, grouped by their
        # /tools section and under the same names the tools carry on /tools
        # and in the footer.
        quick_action_groups=[
            (
                family,
                [
                    {"path": page.path, "label": page.label[locale], "icon": page.icon}
                    for page in chips
                ],
            )
            for family, chips in catalog.quick_action_sections()
        ],
    )


@router.get("/formats")
async def formats_page(request: Request):
    # Ungated, always-present content hub built from the live converter
    # registry. It's the sitemap-listed landing page for format discovery,
    # a real unique-content page (not thin), and the anchor for the future
    # per-pair pages (Phase 2). Category labels are translated in the
    # template; the data is presentation-only.
    return _render(
        request,
        "formats.html",
        format_groups=_grouped_conversions(),
        compress_image=sorted(IMAGE_COMPRESS_FMTS),
        compress_video=sorted(VIDEO_COMPRESS_FMTS),
        # Every matrix chip is a link: to the pair's own page where the
        # catalogue has one, else to the homepage converter pre-set by a
        # "#convert=<src>-to-<tgt>" fragment (app.js) — no page of its own,
        # so no thin pages for search engines. Read per request, like every
        # other catalogue view (G5).
        pair_pages=_pair_pages(),
    )


@router.get("/tools")
async def tools_page(request: Request):
    # Operations-first hub (IA rework PR 2, docs-internal/ia-navigation-konzept.md)
    # — ungated and always-on. Every tool page of the catalogue gets a card,
    # grouped by file type; a gated tool (/redact) drops out with its switch.
    locale = normalize_locale(getattr(request.state, "locale", settings.lang_default))
    return _render(
        request,
        "tools.html",
        content=get_tools_content(locale),
        sections=_tool_sections(locale),
    )


@router.get("/compress")
async def compress_page(request: Request):
    # Image/video target-size landing page (IA rework PR 4) — ungated core
    # OSS feature, same posture as /pdf/{tool} below. Embeds the same tool
    # partial as the homepage, pre-set to Compress mode via preset_mode (a
    # data-attribute read by app.js — see partials/convert_tool.html).
    locale = normalize_locale(getattr(request.state, "locale", settings.lang_default))
    page = catalog.get("/compress")
    return _render(
        request,
        "compress.html",
        content=get_compress_content(locale),
        crumb=page.label[locale],
        related=_related(page.related, locale),
        preset_mode="compress",
    )


@router.get("/convert/video-to-gif")
async def video_to_gif_page(request: Request):
    # Video → GIF (#266) gets one page for every video format, not seven pair
    # pages. Declared before /convert/{pair_slug}, whose slug parser expects a
    # single source format. The converter is pre-set to GIF (preset_target,
    # read by app.js once a video is chosen); it still takes any file.
    locale = normalize_locale(getattr(request.state, "locale", settings.lang_default))
    page = catalog.get("/convert/video-to-gif")
    return _render(
        request,
        "video_to_gif.html",
        content=get_video_gif_content(locale),
        crumb=page.label[locale],
        related=_related(page.related, locale),
        preset_target="gif",
    )


@router.get("/convert/{pair_slug}")
async def convert_pair_page(request: Request, pair_slug: str):
    # Per-pair landing page (Phase 2), e.g. /convert/jpg-to-pdf. The page exists
    # only when it is in the page catalogue, curated content exists in
    # convert_pairs.PAIR_CONTENT AND the conversion is actually registered —
    # anything else 404s, which structurally prevents thin auto-generated pages
    # (penalty-safe). The embedded tool is pre-set to this pair via
    # preset_source/preset_target (read by app.js).
    src, sep, tgt = pair_slug.lower().partition("-to-")
    locale = normalize_locale(getattr(request.state, "locale", settings.lang_default))
    page = catalog.get(f"/convert/{pair_slug.lower()}")
    pair = get_pair_content(src, tgt, locale) if sep and page else None
    if pair is None or tgt not in get_supported_conversions().get(src, []):
        return templates.TemplateResponse(
            request, "404.html", context=localized_context(request), status_code=404
        )
    return _render(
        request,
        "convert_pair.html",
        content=pair,
        crumb=page.label[locale],
        related=_related([f"/convert/{s}-to-{t}" for s, t in related_pairs(src, tgt)], locale),
        preset_source=src,
        preset_target=tgt,
        preset_accept=accept_attr(src),
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
    return _render(request, "contact.html", contact_email=email_mod.operator_recipient())


@router.get("/login")
async def login_page(request: Request):
    return _render_account_page(request, "login.html")


@router.get("/register")
async def register_page(request: Request):
    return _render_account_page(request, "register.html")


@router.get("/forgot-password")
async def forgot_password_page(request: Request):
    return _render_account_page(request, "forgot-password.html")


@router.get("/reset-password")
async def reset_password_page(request: Request):
    return _render_account_page(request, "reset-password.html")


@router.get("/verify-email")
async def verify_email_page(request: Request):
    # NEU-B.3 (slice b): the email link points here. The page-level JS
    # reads the #token= fragment (older links: ?token=) and POSTs it to
    # /api/v1/auth/verify-email so the user sees confirmation in-app.
    return _render_account_page(request, "verify-email.html")


@router.get("/dashboard")
async def dashboard_page(request: Request):
    return _render_account_page(request, "dashboard.html")


@router.get("/account-deleted")
async def account_deleted_page(request: Request):
    # Post-deletion landing page (PR-D): the dashboard "Delete account"
    # flow redirects here after a 204. Not in the nav, not in the sitemap
    # — there is nothing here to crawl.
    return _render_account_page(request, "account_deleted.html")


@router.get("/cancel")
async def cancel_page(request: Request):
    # § 312k BGB "Kündigungsbutton" — the footer link "Cancel contracts here"
    # lands here, and the law only applies where contracts can be concluded
    # online, i.e. Stripe is configured. Without it the page 404s (same shape
    # as /pricing) so a self-host never links or serves a dead cancellation
    # form. Deliberately absent from the sitemap (seo.py): a legal entry point,
    # not landing content. ``contact_email`` feeds the "or send it by email"
    # fallback in the form's error messages (never a dead end).
    # ``minimal_chrome``: BGH I ZR 200/25 — this confirmation page must not
    # carry the site's offer or navigation links, so base.html renders only the
    # logo, language switcher and the © line + Legal group (Impressum/Privacy
    # stay reachable everywhere, DDG § 5).
    if not settings.stripe_secret_key:
        return templates.TemplateResponse(
            request, "404.html", context=localized_context(request), status_code=404
        )
    return _render(
        request,
        "cancel.html",
        contact_email=email_mod.operator_recipient(),
        minimal_chrome=True,
    )


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


@router.get("/redact")
async def redact_page(request: Request):
    # Commercial EE add-on: a build without ai_operations_enabled serves no
    # redaction surface at all (the API 503s too) — same gating shape as /pricing.
    # The catalogue entry carries that gate, so it is the one switch here.
    page = catalog.get("/redact")
    if page is None:
        return templates.TemplateResponse(
            request, "404.html", context=localized_context(request), status_code=404
        )
    locale = normalize_locale(getattr(request.state, "locale", settings.lang_default))
    return _render(
        request,
        "redact.html",
        content=get_redact_content(locale),
        crumb=page.label[locale],
        ai_credit_cost=settings.ai_credit_cost_redact,
        ai_eligible_tiers=settings.ai_eligible_tiers_list,
    )


@router.get("/pdf/{tool}")
async def pdf_tool_page(request: Request, tool: str):
    # Ungated core OSS feature (unlike /redact's commercial gating) — split /
    # extract / compress ride the same free, no-account Convert/Compress
    # posture. The page catalogue is the route whitelist: an unknown tool
    # (e.g. /pdf/rotate) 404s instead of rendering a hollow page.
    locale = normalize_locale(getattr(request.state, "locale", settings.lang_default))
    page = catalog.get(f"/pdf/{tool}")
    content = get_pdf_tool_content(tool, locale) if page else None
    if content is None:
        return templates.TemplateResponse(
            request, "404.html", context=localized_context(request), status_code=404
        )
    return _render(
        request,
        "pdf_tool.html",
        content=content,
        crumb=page.label[locale],
        related=_related(page.related, locale),
        tool=tool,
        pdf_accept=accept_attr("pdf"),
        # /pdf/insert's second file: what the route takes.
        insert_accept=",".join(f".{ext}" for ext in INSERT_FORMATS),
    )


@router.get("/cockpit")
async def cockpit_page(request: Request):
    return _render_account_page(request, "cockpit.html")


@docs_router.get("/docs")
async def api_docs_page(request: Request):
    # The API explorer. FastAPI's built-in /docs (switched off in app/main.py)
    # loaded Swagger UI from a CDN and started it with an inline <script>; the
    # CSP blocks both, so the page rendered empty. This one serves the vendored
    # copy from /static/vendor/ and starts it from /static/js/api-docs.js.
    root_path = request.scope.get("root_path", "").rstrip("/")
    return _render(request, "api_docs.html", openapi_url=root_path + request.app.openapi_url)
