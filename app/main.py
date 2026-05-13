# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import glob
import logging
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.gzip import GZipMiddleware

from app.api.routes import compress, convert, formats, health, pages, seo
from app.api.routes import auth as auth_route
from app.api.routes import billing as billing_route
from app.api.routes import cockpit as cockpit_route
from app.api.routes import keys as keys_route
from app.compat import base_dir, setup_ffmpeg_path
from app.core.assets import tailwind_css_filename
from app.core.config import settings
from app.core.data_classification import (
    REQUEST_HEADER as _DATA_CLASSIFICATION_HEADER,
    RESPONSE_HEADER as _DATA_CLASSIFICATION_RESPONSE_HEADER,
    normalize_classification as _normalize_data_classification,
)
from app.core.i18n import (
    SUPPORTED_LOCALES,
    base_path,
    localized_context,
    localized_url,
    resolve_locale,
)
from app.core.jsonld import build_site_jsonld
from app.core.logging_config import configure_logging
from app.core.metrics import increment as metric_increment
from app.core.rate_limit import limiter
from app.core.templates import templates
from app.converters.registry import _ensure_loaded
from app.db.base import AsyncSessionLocal, engine

# Make bundled ffmpeg available before anything else loads
setup_ffmpeg_path()

# A-9: Structured logging configured before first use
configure_logging(debug=settings.app_debug)

logger = logging.getLogger("filemorph.startup")

_SITE_JSONLD, _SITE_JSONLD_CSP_SOURCE = build_site_jsonld(settings.app_base_url)

# Templates singleton lives in ``app/core/templates.py`` so the pages
# router can import it without pulling main.py (avoids import cycle).
templates.env.globals["api_base_url"] = settings.api_base_url
templates.env.globals["app_base_url"] = settings.app_base_url
templates.env.globals["tailwind_css"] = tailwind_css_filename()
templates.env.globals["site_jsonld"] = _SITE_JSONLD
# Surfaced into templates so the /security page can render the same contact
# alias that /.well-known/security.txt advertises — one source of truth, set
# via SECURITY_CONTACT_EMAIL env-var on each deployment.
templates.env.globals["security_contact_email"] = settings.security_contact_email
# Pricing visibility: self-hosters default to off; SaaS turns it on. Two
# flags so we can run a "Coming Soon" page between launch and Stripe live.
templates.env.globals["pricing_enabled"] = bool(settings.pricing_page_enabled)
templates.env.globals["stripe_enabled"] = bool(settings.stripe_secret_key)

# i18n helpers exposed as Jinja globals so base.html can build the
# language-switcher links and hreflang tags without the route having to
# pre-compute them.
templates.env.globals["supported_locales"] = SUPPORTED_LOCALES
templates.env.globals["localized_url"] = localized_url
templates.env.globals["base_path"] = base_path


def _sweep_stale_temp_dirs(*, max_age_seconds: int) -> int:
    """Remove any ``fm_*`` temp dir older than ``max_age_seconds``.

    Returns the number of dirs swept — useful for tests and for the
    INFO log line at the end of each periodic run. Errors on individual
    dirs are logged at WARNING and do not stop the sweep; a permission
    glitch on one stale dir should not leave the rest behind.

    The request path always cleans its own temp dir in a ``finally``
    block (or via ``BackgroundTask`` on the success path), so this
    sweep only catches crash-recovery cases. The startup pass covers
    process restarts; the periodic pass covers long-running processes
    that stay up across many incidents.
    """
    tmp_root = Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_seconds
    swept = 0
    for stale_dir in glob.glob(str(tmp_root / "fm_*")):
        try:
            p = Path(stale_dir)
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                logger.info("Swept stale temp dir: %s", stale_dir)
                swept += 1
        except Exception:
            logger.warning("Failed to sweep stale temp dir: %s", stale_dir)
    return swept


async def _periodic_temp_sweep(
    *, interval_seconds: int, max_age_seconds: int, stop_event: asyncio.Event
) -> None:
    """Run :func:`_sweep_stale_temp_dirs` on a fixed cadence.

    Wakes up either when the interval elapses or when the lifespan
    asks the loop to stop (via ``stop_event.set()``). Any per-tick
    exception is caught and logged so a transient FS error doesn't
    kill the loop and quietly stop sweeping forever.
    """
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            return
        try:
            _sweep_stale_temp_dirs(max_age_seconds=max_age_seconds)
        except Exception:
            logger.exception("Periodic temp-dir sweep raised; continuing")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(debug=settings.app_debug)
    _ensure_loaded()

    if engine is not None:
        from app.db.base import Base
        import app.db.models  # noqa: F401 — register all ORM models

        # Only bootstrap schema directly for the in-memory test engine.
        # Postgres (prod) is managed by Alembic migrations (`alembic upgrade head`).
        is_memory_sqlite = engine.url.get_backend_name() == "sqlite" and (
            engine.url.database in (None, "", ":memory:")
        )
        if is_memory_sqlite:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("In-memory SQLite schema created for test harness.")
        else:
            logger.info("Database engine configured; schema managed by Alembic.")

    if shutil.which("ffmpeg") is None:
        logger.warning(
            "ffmpeg not found on PATH. Video and audio conversion/compression will not work."
        )

    # A-8 / NEU-B.2: Sweep stale fm_ temp dirs on startup. Crash-recovery
    # only — the request path cleans its own dirs in a ``finally`` block.
    sweep_max_age = max(60, settings.temp_sweep_max_age_minutes * 60)
    _sweep_stale_temp_dirs(max_age_seconds=sweep_max_age)

    # NEU-B.2: keep sweeping while the process runs, so a long-lived
    # worker that survives many incidents does not accumulate orphans.
    sweep_stop = asyncio.Event()
    sweep_task: asyncio.Task | None = None
    if settings.temp_sweep_interval_minutes > 0:
        interval = settings.temp_sweep_interval_minutes * 60
        sweep_task = asyncio.create_task(
            _periodic_temp_sweep(
                interval_seconds=interval,
                max_age_seconds=sweep_max_age,
                stop_event=sweep_stop,
            ),
            name="temp-sweep",
        )

    try:
        yield
    finally:
        sweep_stop.set()
        if sweep_task is not None:
            try:
                await asyncio.wait_for(sweep_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                sweep_task.cancel()


app = FastAPI(
    title="FileMorph",
    description=(
        "Convert and compress files between formats via REST API or Web UI.\n\n"
        "**Authentication**: All API endpoints require the `X-API-Key` header.\n"
        "Generate a key with: `python scripts/generate_api_key.py`"
    ),
    version=settings.app_version,
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# A-2: CORS fix — conditional credentials, restricted methods/headers.
# `expose_headers` is load-bearing for cross-origin downloads: browsers hide
# non-simple response headers from JS unless the server lists them. The Web
# UI reads `Content-Disposition` to derive the download filename; without
# this, the JS fallback kicks in and the saved file has no extension.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=(len(settings.cors_origins_list) > 0 and settings.cors_origins_list != ["*"]),
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization"],
    expose_headers=[
        "Content-Disposition",
        "X-FileMorph-Achieved-Bytes",
        "X-FileMorph-Final-Quality",
        "X-Output-SHA256",
        "X-Data-Classification",
    ],
)

# Compress text responses (HTML, JSON, CSS, JS). Binary file downloads are
# typically already compressed (JPEG/PNG/MP4) so the 1 KB floor avoids
# pointless re-compression overhead on tiny responses.
app.add_middleware(GZipMiddleware, minimum_size=1024)


# A-4: Security headers middleware
def _build_csp_header(api_base_url: str) -> str:
    """Build the CSP header string.

    `connect-src` gates `fetch()` / XHR targets. When the S1.5 upload
    split is active (`API_BASE_URL` set), heavy-upload POSTs go
    cross-origin to the tunnel subdomain — the CSP must list that
    origin or the browser blocks the request before it even hits the
    network. Empty default keeps same-origin deployments with a tight
    `'self'`-only policy.

    Self-hosted Tailwind (see scripts/build-tailwind.sh) lets us drop
    the cdn.tailwindcss.com allowances and the inline-config SHA-256
    hash. `unsafe-inline` stays on style-src because Tailwind-generated
    utility classes still produce inline style for animations/accents.
    """
    connect_src = "'self'"
    if api_base_url:
        connect_src = f"'self' {api_base_url}"
    # Inline JSON-LD blocks need their SHA-256 source-hash on script-src.
    # The hash is derived from the same canonical bytes the template renders,
    # so editing app/core/jsonld.py auto-updates both sides.
    script_src = f"'self' {_SITE_JSONLD_CSP_SOURCE}"
    return (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        f"connect-src {connect_src};"
    )


_CSP_HEADER = _build_csp_header(settings.api_base_url)


# Permissions-Policy disables browser features the app does not need.
# Listing them as empty allow-lists prevents a future XSS or 3rd-party
# inclusion from prompting the user for camera/mic/geolocation. The
# string is static so we build it once at import time.
_PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
)


@app.middleware("http")
async def locale_resolver(request: Request, call_next):
    """Resolve the active locale and stash it on ``request.state``.

    No cookie is written. The URL is the single source of truth — see
    ``app/core/i18n.py`` module docstring for the rationale and the
    privacy-policy commitment ("FileMorph sets no cookies on its own
    domain", ``app/templates/privacy.html`` §6).
    """
    request.state.locale = resolve_locale(request)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = _CSP_HEADER
    # HSTS is meaningful only over HTTPS — ``request.url.scheme`` reflects
    # the proxy-forwarded protocol when ``X-Forwarded-Proto`` is honoured
    # (Caddy / nginx do this by default). Setting it on plain HTTP would
    # be ignored by browsers and noisy in dev.
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = _PERMISSIONS_POLICY
    return response


# S10-lite: paths the page-view counter ignores. Static assets, the API
# surface, and the OpenAPI/docs UI shouldn't count as "someone visited the
# site" — only navigations to user-facing HTML pages do. ``/api/*`` is
# excluded so the convert/compress route counters (per-format-pair) aren't
# double-counted by the generic page-view counter.
_PAGE_VIEW_IGNORED_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/api/",
    "/docs",
    "/openapi",
    "/redoc",
    "/robots.txt",
    "/sitemap.xml",
    "/favicon",
)


@app.middleware("http")
async def page_view_counter(request: Request, call_next):
    """Count one page-view per successful GET to a user-facing HTML page.

    Runs *after* the response so we only count successes (status 200-399).
    ``metric_increment`` owns its own session via ``AsyncSessionLocal``; the
    middleware merely checks the toggle + path filter and never raises.
    """
    response = await call_next(request)
    if (
        AsyncSessionLocal is not None
        and settings.metrics_enabled
        and request.method == "GET"
        and 200 <= response.status_code < 400
        and not any(request.url.path.startswith(p) for p in _PAGE_VIEW_IGNORED_PREFIXES)
    ):
        await metric_increment("page_views")
    return response


@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.max_upload_size_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={
                    "detail": f"File too large. Maximum size: {settings.max_upload_size_mb} MB"
                },
            )
    return await call_next(request)


# NEU-C.3: BSI-style data-classification taxonomy on the request boundary.
# Reads ``X-Data-Classification`` from the caller, validates against the
# fixed vocabulary in :mod:`app.core.data_classification`, stores the
# resolved value on ``request.state`` so convert/compress can include it
# in their audit-log payloads, and echoes it back on the response so the
# caller can verify what the server actually used (which differs from
# the input on invalid values).
@app.middleware("http")
async def data_classification(request: Request, call_next):
    raw = request.headers.get(_DATA_CLASSIFICATION_HEADER)
    classification, was_valid = _normalize_data_classification(raw)
    request.state.data_classification = classification
    if not was_valid:
        # Truncate the rejected value before logging so a 4 KiB header
        # bomb doesn't pollute the structured-log shipper. 64 chars is
        # plenty to identify a typo while bounding the log line.
        rejected = raw[:64] if isinstance(raw, str) else repr(raw)
        logger.warning(
            "data_classification: rejected X-Data-Classification=%r — falling back to %s",
            rejected,
            classification,
        )
    response = await call_next(request)
    response.headers[_DATA_CLASSIFICATION_RESPONSE_HEADER] = classification
    return response


# ── Custom error handlers (A-5) ───────────────────────────────────────────────


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Endpoint not found."}, status_code=404)
    return templates.TemplateResponse(
        request, "404.html", context=localized_context(request), status_code=404
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    logger.exception("Unhandled server error")
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Internal server error."}, status_code=500)
    return templates.TemplateResponse(
        request, "500.html", context=localized_context(request), status_code=500
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Pydantic 2 puts raw exception objects into ``ctx["error"]`` for
    # ValueError-based field validators; ``jsonable_encoder`` renders them
    # to strings so the JSONResponse can serialize the payload.
    return JSONResponse(
        {"detail": "Invalid request parameters.", "errors": jsonable_encoder(exc.errors())},
        status_code=422,
    )


# ── Static files & templates ──────────────────────────────────────────────────

# S1-B: Long-lived cache for content-hashed assets, short revalidate for the
# rest. Regex matches `.abc12345.` or `-abc12345.` — 8+ hex chars sandwiched
# between a separator and the extension dot, the convention emitted by
# esbuild/vite/rollup hash-suffix builds. Matches nothing in the current repo
# (static files are plain), so today everything takes the 5-min branch; the
# immutable branch activates the day a bundler is introduced.
_HASHED_ASSET = re.compile(r"[-.][a-f0-9]{8,}\.")


class CachingStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            if _HASHED_ASSET.search(path):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
        return response


app.mount(
    "/static",
    CachingStaticFiles(directory=str(base_dir() / "app" / "static")),
    name="static",
)


# ── API Routers ───────────────────────────────────────────────────────────────

app.include_router(seo.router)  # /robots.txt and /sitemap.xml at root
app.include_router(health.router, prefix="/api/v1")
app.include_router(formats.router, prefix="/api/v1")
app.include_router(convert.router, prefix="/api/v1")
app.include_router(compress.router, prefix="/api/v1")
app.include_router(auth_route.router, prefix="/api/v1")
app.include_router(keys_route.router, prefix="/api/v1")
app.include_router(billing_route.router, prefix="/api/v1")
app.include_router(cockpit_route.router, prefix="/api/v1")


# ── Web UI ────────────────────────────────────────────────────────────────────
#
# The pages router defines all 14 user-facing HTML routes once. We mount
# it three times so the same handler serves the unprefixed path
# (``x-default`` for SEO, defaults to the operator's ``LANG_DEFAULT``)
# AND the explicit ``/de/...`` + ``/en/...`` prefixes. ``LocaleMiddleware``
# resolves the active locale from the path so the per-request translator
# in :func:`app.core.i18n.localized_context` picks the right ``.mo``.

app.include_router(pages.router)  # /, /pricing, /enterprise, ...
app.include_router(pages.router, prefix="/de")  # /de/, /de/pricing, ...
app.include_router(pages.router, prefix="/en")  # /en/, /en/pricing, ...
