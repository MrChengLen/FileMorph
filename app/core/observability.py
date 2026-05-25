# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prometheus instrumentation — request-path metrics + a domain counter.

Exposes an OpenMetrics endpoint at ``/api/v1/metrics`` that Prometheus
scrapes. Built on the raw ``prometheus-client`` rather than the FastAPI
instrumentator wrapper on purpose: the wrapper pins ``starlette<1.0.0``,
which would hold the dependency below the ``1.0.1`` fix for
PYSEC-2026-161 (Host-header URL-reconstruction). The raw client carries
no such constraint, so the security posture stays clean.

Two layers:

1. **Request-path metrics** recorded by a small middleware:
   - ``http_requests_total{method,handler,status}`` — throughput + error
     rate per route.
   - ``http_request_duration_seconds{method,handler}`` — latency
     histogram for p50/p95/p99.
   The middleware is wired last in ``app/main.py`` so it sits outermost
   and measures full request time (including the other middleware).

2. **Domain counter** ``filemorph_conversions_total{operation,src,tgt,
   status}`` — the per-format-pair view the cockpit already keeps in the
   ``daily_metrics`` table, re-exposed in scrape-friendly form.

Gated by ``settings.metrics_enabled`` (env ``METRICS_ENABLED``, default
true — the same flag the cockpit's analytics card already references).
When false: no middleware, no endpoint — a single-tenant self-hoster who
doesn't run Prometheus pays nothing.

Cardinality safety
------------------
``src`` / ``tgt`` and the request ``handler`` come from request data, so
they are bucketed: formats not in the converter registry collapse to
``"other"`` (``bucket_format``), and an unmatched request path (404)
reports ``handler="other"`` rather than echoing an arbitrary URL. The
label space is therefore bounded by the registered routes and formats,
not by what a caller sends.
"""

from __future__ import annotations

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.converters.registry import get_supported_conversions
from app.core.config import settings

# Scrape + probe traffic is not user traffic; counting it would skew the
# latency percentiles and inflate request counts.
_EXCLUDED_PATHS = frozenset({"/api/v1/metrics", "/api/v1/health", "/api/v1/ready"})

CONVERSIONS_TOTAL = Counter(
    "filemorph_conversions",
    "File conversion/compression operations by format pair and outcome.",
    ["operation", "src", "tgt", "status"],
)

REQUESTS_TOTAL = Counter(
    "http_requests",
    "Total HTTP requests by method, matched route, and status code.",
    ["method", "handler", "status"],
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds by method and matched route.",
    ["method", "handler"],
)

# Registry-derived allowlist, computed lazily on first use so every
# converter module has registered its formats by the time we read it.
_known_formats_cache: frozenset[str] | None = None


def _known_formats() -> frozenset[str]:
    global _known_formats_cache
    if _known_formats_cache is None:
        conv = get_supported_conversions()
        fmts: set[str] = set(conv.keys())
        for targets in conv.values():
            fmts.update(targets)
        _known_formats_cache = frozenset(f.lower() for f in fmts)
    return _known_formats_cache


def bucket_format(fmt: str | None) -> str:
    """Return ``fmt`` lowercased if it's a registry-known format, else ``"other"``."""
    if not fmt:
        return "other"
    lowered = fmt.lower()
    return lowered if lowered in _known_formats() else "other"


def record_conversion(
    operation: str,
    src: str | None,
    tgt: str | None,
    status: str,
    *,
    count: int = 1,
) -> None:
    """Increment the conversions counter with cardinality-capped labels.

    No-op when metrics are disabled, so call sites don't need to guard.
    Never raises — a metric increment is pure in-process bookkeeping, but
    we keep the contract identical to ``metric_increment`` (fire-and-forget)
    so the request path is never at risk from observability code.
    """
    if not settings.metrics_enabled or count <= 0:
        return
    CONVERSIONS_TOTAL.labels(
        operation=operation,
        src=bucket_format(src),
        tgt=bucket_format(tgt),
        status=status,
    ).inc(count)


def _handler_label(request: Request) -> str:
    """Matched-route template (e.g. ``/api/v1/convert``) for the handler
    label, or ``"other"`` when no route matched (404) so a flood of random
    URLs can't explode the time-series count."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "other"


async def _metrics_dispatch(request: Request, call_next):
    if request.url.path in _EXCLUDED_PATHS:
        return await call_next(request)
    start = time.perf_counter()
    status_code = 500  # default if the inner app raises before responding
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        handler = _handler_label(request)
        REQUEST_DURATION.labels(request.method, handler).observe(elapsed)
        REQUESTS_TOTAL.labels(request.method, handler, str(status_code)).inc()


async def _metrics_endpoint(request: Request) -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


_instrumented = False


def setup_metrics(app) -> None:
    """Attach the request-timing middleware and expose ``/api/v1/metrics``.

    Idempotent and gated by ``settings.metrics_enabled``. Call once at
    startup from ``app/main.py``, after all routes are mounted, so the
    middleware sits outermost and measures full request time.
    """
    global _instrumented
    if not settings.metrics_enabled or _instrumented:
        return
    _instrumented = True
    app.add_middleware(BaseHTTPMiddleware, dispatch=_metrics_dispatch)
    app.add_api_route(
        "/api/v1/metrics",
        _metrics_endpoint,
        methods=["GET"],
        include_in_schema=False,
        tags=["System"],
    )
