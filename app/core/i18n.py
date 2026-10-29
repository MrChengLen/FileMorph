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
intact and makes shared URLs deterministic.

``User.preferred_lang`` (PR-i18n-3) is a *separate* axis: it picks the
language for **outbound transactional email**, which is rendered outside
any HTTP request and so has no URL / ``Accept-Language`` signal of its
own. It is seeded from the locale a user registered in and changeable
from the dashboard. It does **not** currently override the web-UI
resolution chain above — making it a sticky web-UI preference for
logged-in users is a tracked follow-up (it would mean teaching the
locale resolver to do a DB lookup, which the cookie-free design
deliberately avoided). See :func:`translator_for`.

The resolved locale lands on ``request.state.locale`` via
:class:`LocaleMiddleware`. Routes that render templates pull it through
:func:`get_locale` (FastAPI dependency) or read it directly from
``request.state``.

Translations are compiled in memory from
``locale/<code>/LC_MESSAGES/messages.po`` once, at startup (``load_catalogs``
in the app's lifespan), and cached for the process. No ``.mo`` files are
committed or built: a binary file in every catalogue change only produced
merge conflicts.
``_()`` is exposed as a template global pointing at the current
request's translator via :func:`localized_context`.

Self-hosters can override the default locale with the ``LANG_DEFAULT``
env-var (read from ``settings.lang_default``) — useful for an EN-first
deployment that doesn't want German fallbacks.
"""

from __future__ import annotations

import gettext
import io
import logging
from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from babel.support import Translations
from fastapi import Request
from jinja2.utils import htmlsafe_json_dumps

from app.core.config import settings
from app.db.base import accounts_enabled

logger = logging.getLogger(__name__)

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


def _compile_catalog(locale: str) -> Translations:
    """Compile ``locale/<locale>/LC_MESSAGES/messages.po`` in memory.

    Same message table as ``pybabel compile``: fuzzy entries are left out, so
    an unreviewed translation falls back to the English source string. The
    placeholder checks ``pybabel compile`` ran are a test instead
    (``tests/test_i18n_catalogs.py``).
    """
    po_path = LOCALE_DIR / locale / "LC_MESSAGES" / "messages.po"
    with po_path.open("rb") as po_file:
        catalog = read_po(po_file, locale=locale, domain="messages")
    mo_bytes = io.BytesIO()
    write_mo(mo_bytes, catalog)
    mo_bytes.seek(0)
    return Translations(mo_bytes, domain="messages")


def _load_translations() -> dict[str, Translations | gettext.NullTranslations]:
    """Load + cache translation bundles for all supported locales.

    A missing or broken ``.po`` falls back to ``NullTranslations`` (identity
    passthrough), logged, so the app still boots and serves the English
    source strings rather than failing every page. The cache is filled in
    one step, so no request sees one locale loaded and the other missing.
    """
    if _translations:
        return _translations
    loaded: dict[str, Translations | gettext.NullTranslations] = {}
    for locale in SUPPORTED_LOCALES:
        try:
            loaded[locale] = _compile_catalog(locale)
        except FileNotFoundError:
            logger.warning("No %s catalogue; serving the English source strings", locale)
            loaded[locale] = gettext.NullTranslations()
        except Exception:
            logger.exception(
                "The %s catalogue failed to load; serving the English source strings", locale
            )
            loaded[locale] = gettext.NullTranslations()
    _translations.update(loaded)
    return _translations


def load_catalogs() -> None:
    """Compile the catalogues now. The app's lifespan calls this once, so the
    first request doesn't pay for it and a broken catalogue shows up in the
    start-up log."""
    _load_translations()


def normalize_locale(locale: str | None) -> str:
    """Coerce an arbitrary string to a supported locale, else the default.

    Used wherever a locale arrives from outside the resolution chain — a
    persisted ``User.preferred_lang`` value, an API request body — and
    must be made safe before it indexes into the translation cache.
    """
    if locale and locale in SUPPORTED_LOCALES:
        return locale
    return _effective_default()


def translator_for(locale: str | None) -> Translations | gettext.NullTranslations:
    """Return the gettext bundle for ``locale`` — no request context needed.

    Outbound email is rendered outside any HTTP request (verification mail
    fired-and-forgotten at register time, dunning mail fired from a Stripe
    webhook), so it can't go through :func:`localized_context`. This is the
    request-free entry point: it normalises the locale first, so an
    unrecognised ``User.preferred_lang`` degrades to the operator default
    rather than raising.
    """
    return _load_translations().get(normalize_locale(locale)) or gettext.NullTranslations()


def gettext_noop(message: str) -> str:
    """Mark a string for extraction without translating it at call time.

    ``pybabel extract`` picks up ``N_(...)`` calls by default, so this lets
    a module-level constant (e.g. an email *subject* line, which never
    passes through a Jinja template) land in the ``.pot`` file. The actual
    translation happens later via ``translator_for(locale).gettext(...)``.
    """
    return message


# Conventional alias — babel's default keyword list includes ``N_``.
N_ = gettext_noop


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


def _js_i18n_strings(_: gettext.GNUTranslations.gettext) -> dict[str, str]:
    """Catalogue of strings the front-end JS files need at runtime.

    Server-rendered as a JSON blob in ``base.html`` and exposed as
    ``window.FM_I18N`` to every page. JS files reference these instead of
    hardcoding English literals (e.g. ``alert(window.FM_I18N.alertNoFiles)``
    instead of ``alert('Please select at least one file.')``).

    Adding a string here:
      1. add the ``"key": _('English source string')`` line below,
      2. use ``window.FM_I18N.key`` from the JS file,
      3. run ``python scripts/i18n.py extract && update`` and translate
         the new msgid in ``locale/de/LC_MESSAGES/messages.po``.

    Sorted alphabetically per-section so a future ``git diff`` stays
    review-friendly.
    """
    accounts = accounts_enabled()
    return {
        # app.js — convert/compress UI
        "alertInconsistentTarget": _(
            "Target format selection is inconsistent — please reselect your files."
        ),
        "alertNoFiles": _("Please select at least one file."),
        "alertNoTargetAvailable": _(
            "One of the files has no target format available. Remove it to proceed."
        ),
        "alertNoTargetFormat": _("Please select a target format."),
        "alertNoTargetSize": _("Please enter a target size in MB."),
        # The hint for a target that grows the file; {factor} is "5–10×" or "~11×".
        "amplifySuggest": _("Use {format} instead →"),
        "amplifyWarning": _(
            "Heads up: {target} output is typically {factor} larger than the source."
        ),
        # Screen-reader labels of a file row; {name} is the file name.
        "ariaRemoveFile": _("Remove {name}"),
        "ariaTargetFormatFor": _("Target format for {name}"),
        "chooseTargetFormat": _("— choose a target format —"),
        "compress": _("Compress"),
        "compression": _("Compression"),
        "convert": _("Convert"),
        "downloadResult": _("Download Result"),
        "downloadResultSize": _("Download Result ({size} MB)"),
        "downloadZip": _("Download ZIP ({count} files)"),
        "fileCountMany": _("{count} files · {size} total"),
        "fileCountOne": _("1 file · {size}"),
        "noConversionsAvailable": _("No conversions available for this format"),
        "noTargetsOption": _("— no targets —"),
        # Pre-set pages and "#convert=<src>-to-<tgt>" links (from /formats);
        # app.js fills in {src}, {tgt} and {ext}, upper case, as plain text.
        "presetMismatch": _(
            "This file is {ext}, but the preset is {src} to {tgt}. Choose a target "
            "below, or your {src} file."
        ),
        "presetMismatchTarget": _(
            "This file is {ext} and can't become {tgt}. Choose a target below."
        ),
        "presetReady": _("Preset: {src} to {tgt}. Choose your {src} file."),
        "progressBatch": _("Processing {count} files…"),
        "progressSingle": _("Processing your file…"),
        "quality": _("Quality"),
        "selectFileFirst": _("— select a file first —"),
        # docx→pdf engine routing — pre-upload notice + post-convert warnings.
        # Surface fidelity-affecting decisions in the UI instead of stuffing
        # them into the PDF artefact (which the user forwards to recipients).
        "docxPdfEngineNotice": _(
            "Complex Word features (footnotes, headers/footers, "
            "table-of-contents, multi-section layout, multi-level lists) "
            "auto-route to the high-fidelity engine when the office image "
            "is deployed. The slim image uses a fallback pipeline that "
            "simplifies these features."
        ),
        "docxPdfEngineLearnMore": _("Engine details ↗"),
        "conversionWarningTitle": _("Conversion completed with notes"),
        "compressionWarningTitle": _("Compressed — with a note"),
        # Target-size notes (compress.py::target_notes), single file and batch.
        "warningTargetResized": _(
            "Scaled down to {width} × {height} pixels — the lowest quality alone "
            "wasn't enough for the target size."
        ),
        "warningTargetMissed": _(
            "The target size can't be reached, not even by scaling the image down: "
            "you get it at the lowest quality, still larger than the target."
        ),
        "warningEngineFallback": _(
            "The high-fidelity LibreOffice engine wasn't available on "
            "this deployment — output uses the pure-Python fallback "
            "pipeline, which simplifies complex Word features."
        ),
        "warningSimplifiedFootnotes": _("Footnotes were simplified"),
        "warningSimplifiedEndnotes": _("Endnotes were simplified"),
        "warningSimplifiedHeaders": _("Page headers were simplified"),
        "warningSimplifiedFooters": _("Page footers were simplified"),
        "warningSimplifiedOle": _(
            "Embedded objects (Excel charts, Visio diagrams) were simplified"
        ),
        "warningSimplifiedSections": _("Multi-section page layout was simplified"),
        "warningSimplifiedEquations": _("Equations were simplified"),
        "warningSimplifiedMultilevel": _("Multi-level numbered lists were flattened"),
        # A feature the list above doesn't know yet, by its server name.
        "warningSimplifiedOther": _("Simplified: {feature}"),
        "warningFidelityReduced": _("Some document elements were simplified during conversion"),
        # 413 disambiguation — distinguishes "your upload was too big"
        # (before any work) from "the rendered output exceeded the cap"
        # (after conversion). Same status code; very different remediation.
        # The free paths only — the hosted service has no paid plan to upgrade
        # to. The UI doesn't know the caller's tier here, so the texts name
        # self-hosting for everyone and the free account for visitors without one
        # (the server's own messages pick one path per tier) — the account only
        # where accounts exist: a Community Edition instance has none.
        "errorInputTooLarge": (
            _(
                "File too large. Use a smaller file or self-host FileMorph — there you "
                "set the limits. No account yet? Register free for larger files."
            )
            if accounts
            else _(
                "File too large. Use a smaller file or self-host FileMorph — there you "
                "set the limits."
            )
        ),
        "errorOutputCapExceeded": (
            _(
                "The result would be larger than allowed. Try a more efficient target "
                "format or a lower quality, or self-host FileMorph — there you set the "
                "limits. No account yet? Register free for a higher limit."
            )
            if accounts
            else _(
                "The result would be larger than allowed. Try a more efficient target "
                "format or a lower quality, or self-host FileMorph — there you set the "
                "limits."
            )
        ),
        # The same code for a GIF made from a video: its size and frame rate
        # are fixed, so only a shorter clip makes it smaller.
        "errorOutputCapGif": (
            _(
                "The GIF would be larger than allowed. Use a shorter clip, or self-host "
                "FileMorph — there you set the limits. No account yet? Register free for "
                "a higher limit."
            )
            if accounts
            else _(
                "The GIF would be larger than allowed. Use a shorter clip, or self-host "
                "FileMorph — there you set the limits."
            )
        ),
        "errorTargetSizeExceedsCap": (
            _(
                "The target size is above the output limit. Choose a smaller target "
                "size or self-host FileMorph — there you set the limits. No account "
                "yet? Register free for a higher limit."
            )
            if accounts
            else _(
                "The target size is above the output limit. Choose a smaller target "
                "size or self-host FileMorph — there you set the limits."
            )
        ),
        # X-FileMorph-Error-Code: batch_too_large — /convert/batch and
        # /compress/batch over the tier's files per request. The numbers are
        # the anonymous and free batch sizes in app/core/quotas.py; a test pins
        # them. Without accounts the web UI is always anonymous (no key field,
        # no login), so "one file at a time" is exact there.
        "errorBatchTooLarge": (
            _(
                "Too many files at once. Select fewer files or self-host FileMorph — "
                "there you set the limits. No account yet? Then it's one file at a "
                "time — register free for up to 10 at once."
            )
            if accounts
            else _(
                "Too many files at once. Select one file at a time or self-host "
                "FileMorph — there you set the limits."
            )
        ),
        # X-FileMorph-Error-Code: video_too_long / video_too_complex — /convert
        # video → GIF (VideoTooLongError / VideoTooComplexError in
        # app/converters/base.py; a test pins the 30 seconds).
        "errorVideoTooLong": _(
            "This video is longer than 30 seconds, the maximum for a GIF. Shorten it to "
            "30 seconds or less (for example in your phone's gallery or a video editor), "
            "or convert it to MP4 or WebM instead."
        ),
        "errorVideoTooComplex": _(
            "This video is too large to turn into a GIF in time. Use a shorter clip or "
            "a lower resolution (for example 1080p), then try again."
        ),
        # Other failed requests; {status} is the HTTP status, {detail} the
        # browser's own error text.
        "errorConversionFailed": _("Conversion failed (status {status})."),
        "errorFileTooLarge": _("File too large."),
        "errorInvalidApiKey": _("Invalid API key. Check your key and try again."),
        "errorNetwork": _("Network error: {detail}"),
        "errorTooManyRequests": _("Too many requests. Please wait a moment and try again."),
        # X-FileMorph-Error-Code for the server's own English texts, read by
        # app.js and pdf-tools.js (decompression_bomb: pdfImageTooLarge below).
        # convert_failed, compress_failed and server_busy word them as the
        # server does; file_type_not_permitted says why and what next;
        # request_too_large (the upload cap no account lifts) takes its {max}
        # from the body's max_size_mb, and a batch counts its files together.
        "errorCompressFailed": _(
            "Compression failed. Verify your file is valid and the format is supported."
        ),
        "errorConvertFailed": _(
            "Conversion failed. Verify your file is valid and the format is supported."
        ),
        "errorFileTypeNotPermitted": _(
            "File type not permitted. This file starts like a program or script, whatever "
            "its name says. Choose a file in one of the supported formats."
        ),
        "errorRequestTooLarge": _(
            "File too large: this server takes at most {max} MB per upload. Use a smaller "
            "file or self-host FileMorph — there you set the limits."
        ),
        "errorRequestTooLargeBatch": _(
            "Too large together: this server takes at most {max} MB per upload, all files "
            "together. Select fewer or smaller files, or self-host FileMorph — there you "
            "set the limits."
        ),
        "errorServerBusy": _(
            "FileMorph is at capacity. The request was not processed; retry in a few seconds."
        ),
        # pdf-tools.js — the 2 GB form ceiling no account or self-host lifts
        "errorTargetSizeTooHigh": _("The target size is above the allowed maximum of 2 GB."),
        # P2-1 — batch result summary on /batch responses. The template
        # placeholders are kept stable across translations so the JS can
        # do a token substitution without per-locale parsing.
        "batchSummaryCounts": _("{succeeded} of {total} files succeeded ({failed} failed)"),
        # A batch where every file failed: {error} is the first file's message.
        "batchAllFailed": _("All files failed."),
        "batchFailed": _("Batch failed: {failed}/{total} files. First error: {error}"),
        # Stand-ins in the per-file lists when the server's list is cut short
        # or a file name can't be read.
        "batchMoreInManifest": _("(more — see manifest.json inside the ZIP)"),
        "batchUnknownName": _("(unknown)"),
        "batchUnparseable": _("(unparseable)"),
        # dashboard.js — API-key management
        "copied": _("Copied!"),
        "copy": _("Copy"),
        "created": _("Created"),
        "creating": _("Creating…"),
        "lastUsed": _("Last used"),
        "neverUsed": _("Never used"),
        "newKey": _("+ New Key"),
        "noApiKeys": _("No API keys yet. Create one above."),
        "revoke": _("Revoke"),
        "revokeConfirm": _("Revoke this API key? This cannot be undone."),
        # cockpit.js / cockpit-metrics.js — admin tool
        "deleteFailed": _("Delete failed."),
        "noConversionsYet": _("No conversions yet."),
        "noJobsToday": _("No conversion or compression jobs today yet."),
        "saveFailed": _("Save failed."),
        "softDeleteConfirm": _("Soft-delete this user (sets is_active=false)?"),
        # forgot-password.js / login.js / register.js — auth flows
        "createAccount": _("Create Account"),
        "creatingAccount": _("Creating account…"),
        "loginFailed": _("Login failed."),
        "passwordTooShort": _("Password must be at least 8 characters."),
        "passwordsDontMatch": _("Passwords do not match."),
        "registrationFailed": _("Registration failed."),
        "sending": _("Sending…"),
        "signIn": _("Sign In"),
        "signingIn": _("Signing in…"),
        # pricing.js — Stripe upgrade buttons
        "paymentsNotActive": _("Payments are currently not available."),
        "redirecting": _("Redirecting…"),
        "upgradeToBusiness": _("Upgrade to Business"),
        "upgradeToPro": _("Upgrade to Pro"),
        # auth.js — dynamic nav after login
        "dashboard": _("Dashboard"),
        "signOut": _("Sign Out"),
        # redact.js — PII redaction tool (/redact). Entity labels are keyed by the
        # stable detector IDs (redactEntity<TYPE>) so the JS maps them directly.
        "redactScan": _("Scan for PII"),
        "redactScanning": _("Scanning…"),
        "redactApply": _("Redact & download"),
        "redactApplying": _("Redacting…"),
        "redactNoFindings": _("No PII detected in this file."),
        "redactFindings": _("{count} item(s) found"),
        "redactCreditCost": _("Costs {n} credit per file"),
        "redactCreditsRemaining": _("{n} credits remaining"),
        "redactPaidTitle": _("Downloading the redacted file needs a paid plan"),
        "redactPaidBody": _(
            "You've seen the findings above. Redacting and downloading the file "
            "requires a Pro or Business plan."
        ),
        "redactInsufficientCredits": _(
            "Out of redaction credits — upgrade your plan or wait for the monthly reset."
        ),
        "redactVerifyFailed": _(
            "Redaction could not be verified — no file was produced. Please try again."
        ),
        "redactUnsupported": _("Unsupported file. Supported: TXT, DOCX, XLSX."),
        "redactUnavailable": _("Redaction is not available on this deployment."),
        "redactError": _("Redaction failed. Please try again."),
        "redactPhoneReview": _("Phone numbers are lower-confidence — review before redacting."),
        "redactEntityEMAIL": _("Email address"),
        "redactEntityIBAN": _("IBAN"),
        "redactEntityPHONE": _("Phone number"),
        "redactEntityIPV4": _("IPv4 address"),
        "redactEntityCREDIT_CARD": _("Credit-card number"),
        "redactRegister": _("Register free"),
        "redactSeePricing": _("See plans"),
        "redactDownload": _("Download redacted file"),
        "redactAnother": _("Redact another file"),
        # pdf-tools.js — /pdf/split, /pdf/extract, /pdf/compress, /pdf/insert.
        # The compress-honesty keys carry the achieved size via a "{size}"
        # token, substituted the same way as redact's "{count}"/"{n}" tokens.
        "pdfToolError": _("Something went wrong. Please try again."),
        "pdfSelectFile": _("Select a PDF file first."),
        "pdfNotAPdf": _("Please select a PDF file."),
        "pdfInvalidFile": _("Could not read the PDF. Verify the file is valid."),
        # X-FileMorph-Error-Code: pdf_encrypted — also read by app.js, since
        # /convert sends the same code (PDF → TXT, PDF → PDF/A).
        "pdfEncrypted": _(
            "This PDF is password-protected. Remove the password "
            "(e.g. open the file and print it to a new PDF) and try again."
        ),
        # X-FileMorph-Error-Code: pdf_encryption_unsupported (certificate, DRM
        # or an unsupported method) — read by pdf-tools.js and app.js too.
        "pdfEncryptionUnsupported": _(
            "This PDF is protected with a certificate or an unsupported encryption. "
            "Remove the protection (e.g. ask the sender for an unprotected copy) and try again."
        ),
        "pdfInvalidSelection": _(
            "Invalid page selection. Use 1-based page numbers and ranges, e.g. '1-3,5'."
        ),
        # X-FileMorph-Error-Code: pdf_too_many_pages — one code from split and
        # extract, so pdf-tools.js picks the text by tool (the next step differs).
        # The number is _MAX_SELECTION_PAGES (app/converters/pdf_pages.py); a
        # test pins it.
        "pdfTooManyPagesSplit": _(
            "This PDF has more than 10,000 pages — too many to split at once. "
            "Extract up to 10,000 pages at a time with “Extract PDF pages”, "
            "then split each part."
        ),
        "pdfTooManyPagesExtract": _(
            "You can extract at most 10,000 pages at once. "
            "Select fewer pages, or extract them in several parts."
        ),
        # X-FileMorph-Error-Code: pdf_too_complex — /pdf/compress past the
        # child process's memory, time or file size limits; the compress page
        # shows the link to the extract tool next to it.
        "pdfTooComplex": _(
            "This PDF is too large or complex to compress in one go. "
            "Extract fewer pages at a time with “Extract PDF pages”, "
            "then compress each part."
        ),
        "pdfRateLimited": _("Too many requests. Please wait a moment and try again."),
        "pdfCompressAchieved": _("Compressed to {size} MB"),
        "pdfCompressNotConverged": _(
            "Couldn't fully reach your target size — best achieved: {size} MB."
        ),
        "pdfCompressNoImages": _(
            "Nothing to recompress — this PDF has no images that can be shrunk. Size: {size} MB."
        ),
        # X-FileMorph-Warnings: scaled=<percent> from /pdf/compress.
        "pdfCompressScaled": _(
            "The images in the PDF were scaled down to {percent} percent of their resolution — "
            "the lowest quality alone wasn't enough for the target size. "
            "Text and layout are unchanged."
        ),
        # Compress no-op branch (X-FileMorph-Recompressible-Images: 0) relabels
        # the download button so it never implies a compression that didn't
        # happen — see showCompressHonesty() in pdf-tools.js.
        "pdfDownloadUnchanged": _("Download unchanged file"),
        # /pdf/insert (pdf-tools.js): which input an error is about
        # (X-FileMorph-Error-Field), where the pages go, and the result.
        "pdfFieldFile": _("Your PDF"),
        "pdfFieldInsert": _("File to insert"),
        "pdfFieldPosition": _("Position"),
        "pdfSelectInsertFile": _("Choose the file to insert."),
        "pdfEnterPage": _("Enter the page after which the new pages go."),
        "pdfPositionStart": _("The new pages start at page 1."),
        "pdfPositionAfter": _("The new pages start at page {page}."),
        "pdfPositionEnd": _("The new pages go after the last page."),
        "pdfInsertedOne": _("1 page inserted — now {total} pages, {size}."),
        "pdfInsertedMany": _("{inserted} pages inserted — now {total} pages, {size}."),
        "pdfWithInserted": _("{name} (with the inserted pages)"),
        "pdfInvalidPosition": _("Your PDF has {count} pages — choose a page from 1 to {count}."),
        "pdfInvalidPositionOne": _(
            "Your PDF has only 1 page — choose “At the start” or “At the end”."
        ),
        "pdfInsertUnsupported": _(
            "This file can't be inserted. Insert a PDF, a Word file (.docx) or an image "
            "(JPG, PNG, HEIC …); save other documents as .docx or PDF first."
        ),
        "pdfWordNotConverted": _(
            "This Word file couldn't be converted here. In Word, save it as a PDF "
            "(File → Save as → PDF) and insert the PDF."
        ),
        # Also app.js: /convert and /compress send the same code (decompression_bomb).
        "pdfImageTooLarge": _(
            "The image is too large to process safely. Make it smaller and try again."
        ),
        "pdfInsertUnreadable": _(
            "The image couldn't be read. Save it as PNG or JPG and try again."
        ),
        "pdfTooManyPagesInsert": _(
            "Together the files would have more than 10,000 pages — too many for one insertion."
        ),
        "pdfTooComplexInsert": _(
            "These files are too large or complex to combine in one go. Insert into a smaller "
            "part of the PDF (“Extract PDF pages”), or shrink the files first with “Compress PDF”."
        ),
    }


def localized_context(request: Request, **extra) -> dict:
    """Build a context dict carrying the per-request translator + locale.

    Pass into ``templates.TemplateResponse(..., context=localized_context(request, ...))``
    so ``{{ _('Sign In') }}`` resolves against the right catalogue and the
    template can read ``{{ locale }}`` directly.

    ``current_prefix`` is the URL path's actual locale prefix (``'de'``,
    ``'en'``, or ``None`` for the unprefixed ``x-default`` route). Nav
    templates use ``localized_url('/pricing', current_prefix)`` so links
    keep the user in their currently-prefixed namespace — clicking
    ``Pricing`` from ``/de/login`` lands on ``/de/pricing``, from
    ``/login`` (no prefix) lands on ``/pricing``.

    ``js_i18n_json`` is the JS-side string catalogue, JSON-encoded so
    ``base.html`` can drop it into a ``<script type="application/json">``
    block without quote-escape hazards; ``htmlsafe_json_dumps`` (the escaping
    behind Jinja's ``|tojson``) writes ``<``, ``>``, ``&`` and ``'`` as JSON
    escapes, so no translation can end the block. See ``_js_i18n_strings``.
    """
    # Lazy imports: both modules import this one (normalize_locale), so a
    # top-level import here would be circular. By request time all are loaded.
    from app.core import catalog
    from app.core.convert_pairs import format_label

    locale = getattr(request.state, "locale", None) or resolve_locale(request)
    translator = _load_translations().get(locale) or gettext.NullTranslations()
    current_prefix = path_prefix_locale(request.url.path)
    # The footer's two catalogue views, read per request so a switch decides
    # the footer the same way it decides the page (G5).
    footer_convert_links = []
    for page in catalog.pages(kind="convert"):
        src, tgt = catalog.pair_of(page.path)
        footer_convert_links.append(
            {"label": f"{format_label(src)} → {format_label(tgt)}", "path": page.path}
        )
    footer_tool_links = [
        {"label": page.label[normalize_locale(locale)], "path": page.path}
        for page in catalog.footer_tools()
    ]
    ctx = {
        "_": translator.gettext,
        "gettext": translator.gettext,
        "ngettext": translator.ngettext,
        "locale": locale,
        "current_prefix": current_prefix,
        "base_path": base_path(request.url.path),
        "localized_url": localized_url,
        "footer_convert_links": footer_convert_links,
        "footer_tool_links": footer_tool_links,
        "js_i18n_json": str(
            htmlsafe_json_dumps(_js_i18n_strings(translator.gettext), ensure_ascii=False)
        ),
    }
    ctx.update(extra)
    return ctx
