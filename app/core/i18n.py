# SPDX-License-Identifier: AGPL-3.0-or-later
"""i18n primitives — locale resolution + per-request translator binding.

Resolution chain (highest priority first):

1. URL path-prefix (``/de/...`` or ``/en/...``)
2. Query-param (``?lang=de|en``)
3. ``Accept-Language`` header (``de*`` | ``en*``)
4. Default ``de`` (Hamburg-based operator, see plan)

The app stores **no client-side locale preference** (no cookie, no
localStorage). The URL is the single source of truth: a user who clicks
the EN switcher lands on ``/en/...`` and stays there as long as
in-app links propagate ``current_prefix``. A return visit to an
unprefixed URL falls through to ``Accept-Language`` and the operator
default. This keeps the published privacy guarantee ("no cookies")
intact and makes shared URLs deterministic. Logged-in users get a
sticky preference via ``User.preferred_lang`` (PR-i18n-3) — server-side,
device-portable, strictly better than a cookie.

The resolved locale lands on ``request.state.locale`` via
:class:`LocaleMiddleware`. Routes that render templates pull it through
:func:`get_locale` (FastAPI dependency) or read it directly from
``request.state``.

Translations are loaded once at import time from
``locale/<code>/LC_MESSAGES/messages.mo``. ``_()`` is exposed as a
template global pointing at the current request's translator via
:func:`localized_context`.

Self-hosters can override the default locale with the ``LANG_DEFAULT``
env-var (read from ``settings.lang_default``) — useful for an EN-first
deployment that doesn't want German fallbacks.
"""

from __future__ import annotations

import gettext
from pathlib import Path

from babel.support import Translations
from fastapi import Request

from app.core.config import settings

SUPPORTED_LOCALES: tuple[str, ...] = ("de", "en")
DEFAULT_LOCALE: str = "de"
LOCALE_DIR: Path = Path(__file__).resolve().parent.parent.parent / "locale"

# Module-level translation cache. Populated lazily on first lookup.
_translations: dict[str, Translations | gettext.NullTranslations] = {}


def _effective_default() -> str:
    """Return the operator-configured default locale, falling back to DE.

    ``settings.lang_default`` lives in ``app/core/config.py``. Self-hosters
    can flip the default to EN via the ``LANG_DEFAULT`` env-var without
    touching the code.
    """
    candidate = getattr(settings, "lang_default", DEFAULT_LOCALE)
    if candidate in SUPPORTED_LOCALES:
        return candidate
    return DEFAULT_LOCALE


def _load_translations() -> dict[str, Translations | gettext.NullTranslations]:
    """Load + cache translation bundles for all supported locales.

    A missing ``.mo`` falls back to ``NullTranslations`` (identity
    passthrough) so the app boots even before ``pybabel compile`` has
    been run — useful for the very first dev setup.
    """
    if _translations:
        return _translations
    for locale in SUPPORTED_LOCALES:
        try:
            t = Translations.load(LOCALE_DIR, locales=[locale], domain="messages")
        except (FileNotFoundError, OSError):
            t = gettext.NullTranslations()
        _translations[locale] = t
    return _translations


def path_prefix_locale(path: str) -> str | None:
    """Return ``de`` / ``en`` if the path starts with that prefix, else ``None``."""
    parts = path.split("/", 2)
    if len(parts) >= 2 and parts[1] in SUPPORTED_LOCALES:
        return parts[1]
    return None


def base_path(path: str) -> str:
    """Strip the locale-prefix from a path. ``/de/pricing`` → ``/pricing``."""
    parts = path.split("/", 2)
    if len(parts) >= 2 and parts[1] in SUPPORTED_LOCALES:
        return "/" + (parts[2] if len(parts) > 2 else "")
    return path


# Some pages have a locale-specific URL spelling — typically when the
# canonical German URL is a German word that English readers don't
# recognise. The map is keyed by the canonical (German-side) path; each
# value maps a target locale to the alias path for that locale. The
# unprefixed/x-default URL always uses the canonical key.
_PATH_ALIASES: dict[str, dict[str, str]] = {
    "/impressum": {"en": "/imprint"},
}
# Reverse map (any alias → canonical) lets ``localized_url`` accept a
# URL in either spelling and route it correctly. Computed once at import.
_PATH_ALIASES_REVERSE: dict[str, str] = {
    alias: canonical
    for canonical, by_locale in _PATH_ALIASES.items()
    for alias in by_locale.values()
}


def localized_url(base: str, locale: str | None) -> str:
    """Build a URL for a given base path and locale.

    ``locale=None`` returns the unprefixed (x-default) URL on the
    canonical spelling. For locales that have an alias in ``_PATH_ALIASES``
    the locale-specific spelling is used (e.g. ``/impressum`` → ``/en/imprint``).

    The language switcher in ``base.html`` passes the current request's
    ``base_path`` here, which may already be in alias form (``/imprint``
    when the user is on ``/en/imprint``). We normalise to the canonical
    key first via ``_PATH_ALIASES_REVERSE`` so a 'switch to DE' link from
    ``/en/imprint`` correctly produces ``/de/impressum``.
    """
    base = base or "/"
    if not base.startswith("/"):
        base = "/" + base
    # Step 1: if the input is already an alias (e.g. /imprint),
    # collapse it to the canonical (e.g. /impressum) so the rest of
    # the logic operates on a single key.
    canonical = _PATH_ALIASES_REVERSE.get(base, base)
    # Step 2: if the target locale has an alias for this canonical,
    # use it (e.g. /impressum + en → /imprint).
    if locale is not None and canonical in _PATH_ALIASES:
        target = _PATH_ALIASES[canonical].get(locale, canonical)
    else:
        target = canonical
    if locale is None:
        return target
    if target == "/":
        return f"/{locale}/"
    return f"/{locale}{target}"


def _accept_language_locale(header: str | None) -> str | None:
    """Best-effort parse of an ``Accept-Language`` header to ``de`` / ``en`` / ``None``.

    A real parser would weigh q-values; for two languages the leading
    tag is enough — and matches the browser's primary preference in
    >99% of real headers.
    """
    if not header:
        return None
    h = header.lower().strip()
    if h.startswith(("de", "de-")):
        return "de"
    if h.startswith(("en", "en-")):
        return "en"
    return None


def resolve_locale(request: Request) -> str:
    """Run the resolution chain and return the active locale string."""
    # 1. URL path-prefix wins
    prefix = path_prefix_locale(request.url.path)
    if prefix:
        return prefix
    # 2. Explicit query-param
    q = request.query_params.get("lang")
    if q in SUPPORTED_LOCALES:
        return q
    # 3. Best-effort Accept-Language
    al = _accept_language_locale(request.headers.get("accept-language"))
    if al:
        return al
    # 4. Operator default (DE unless overridden)
    return _effective_default()


async def get_locale(request: Request) -> str:
    """FastAPI dependency: read the locale resolved by middleware.

    Falls back to the resolution chain if middleware didn't run (tests
    that exercise routes without going through the full ASGI stack).
    """
    return getattr(request.state, "locale", None) or resolve_locale(request)


def localized_context(request: Request, **extra) -> dict:
    """Build a context dict carrying the per-request translator + locale.

    Pass into ``templates.TemplateResponse(..., context=localized_context(request, ...))``
    so ``{{ _('Sign In') }}`` resolves against the right ``.mo`` and the
    template can read ``{{ locale }}`` directly.

    ``current_prefix`` is the URL path's actual locale prefix (``'de'``,
    ``'en'``, or ``None`` for the unprefixed ``x-default`` route). Nav
    templates use ``localized_url('/pricing', current_prefix)`` so links
    keep the user in their currently-prefixed namespace — clicking
    ``Pricing`` from ``/de/login`` lands on ``/de/pricing``, from
    ``/login`` (no prefix) lands on ``/pricing``.
    """
    locale = getattr(request.state, "locale", None) or resolve_locale(request)
    translator = _load_translations().get(locale) or gettext.NullTranslations()
    current_prefix = path_prefix_locale(request.url.path)
    ctx = {
        "_": translator.gettext,
        "gettext": translator.gettext,
        "ngettext": translator.ngettext,
        "locale": locale,
        "current_prefix": current_prefix,
        "base_path": base_path(request.url.path),
        "localized_url": localized_url,
    }
    ctx.update(extra)
    return ctx
