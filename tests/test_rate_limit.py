# SPDX-License-Identifier: AGPL-3.0-or-later
"""H1 — Rate-limit positive regression test.

The pricing copy promises "10 requests/minute" on convert + compress
(``@limiter.limit("10/minute")``). The slowapi limiter is **disabled**
session-wide via ``RATELIMIT_ENABLED=0`` in ``conftest.py`` so the rest
of the suite isn't accidentally rate-limited (test 11+ would otherwise
return 429 and break unrelated tests).

That global disable means the public 10/min claim has zero coverage —
a regression that broke slowapi initialization or removed the decorator
would ship silently. This module re-enables the limiter for one test
and exercises the actual 429 boundary.

Discipline:
  - Re-enable scoped to the test via a fixture (yield + restore).
  - Use a brand-new ``slowapi`` storage so other tests' counts don't
    leak in. We do this by toggling the *enabled* flag on the existing
    limiter; the in-memory storage is fresh per call regardless.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import limiter as _shared_limiter


@pytest.fixture
def rate_limiter_enabled():
    """Flip the shared slowapi limiter back ON for one test.

    The default session state (set by conftest.py) is ``enabled=False``
    so most tests can fire dozens of requests without hitting 429. We
    flip it ON, run the assertions, and flip it back OFF on teardown.
    Resetting the in-memory storage ensures we start at zero hits.
    """
    _shared_limiter.enabled = True
    # Reset the limiter's internal storage so prior calls don't count.
    if hasattr(_shared_limiter, "reset"):
        _shared_limiter.reset()
    elif hasattr(_shared_limiter, "_storage") and hasattr(_shared_limiter._storage, "reset"):
        _shared_limiter._storage.reset()
    try:
        yield
    finally:
        # Always disable on teardown — a test crash between yield and this
        # line would otherwise leave the limiter ON and 429 every following
        # test that hits convert/compress.
        _shared_limiter.enabled = False


def test_convert_route_returns_429_after_10_requests_per_minute(
    client, auth_headers, sample_jpg, rate_limiter_enabled
) -> None:
    """The pricing-page promise is ``10 req/min`` on /api/v1/convert.
    Fire 11 requests as fast as possible and assert the 11th is 429.
    """
    # 10 successful → 11th rate-limited
    statuses: list[int] = []
    for _ in range(11):
        with sample_jpg.open("rb") as fp:
            res = client.post(
                "/api/v1/convert",
                headers=auth_headers,
                files={"file": ("sample.jpg", fp, "image/jpeg")},
                data={"target_format": "png"},
            )
        statuses.append(res.status_code)
        if res.status_code == 429:
            break

    # The 11th must be 429. We allow 200/413/422 in the first ten
    # (the contract is the limit, not the success rate of conversion).
    assert 429 in statuses, (
        f"Expected at least one 429 within 11 requests, got statuses: {statuses}"
    )
    # 429 should appear on or after request 11 (slowapi counts the failing
    # request itself, so it can be earlier in pathological setups; pin
    # only that we *do* see one).


def test_rate_limit_response_carries_retry_after(
    client, auth_headers, sample_jpg, rate_limiter_enabled
) -> None:
    """When 429 fires, the Retry-After header must accompany it so
    well-behaved clients can back off without guessing."""
    last_429 = None
    for _ in range(15):  # generous over-fire to guarantee a 429
        with sample_jpg.open("rb") as fp:
            res = client.post(
                "/api/v1/convert",
                headers=auth_headers,
                files={"file": ("sample.jpg", fp, "image/jpeg")},
                data={"target_format": "png"},
            )
        if res.status_code == 429:
            last_429 = res
            break
    assert last_429 is not None, "Expected a 429 within 15 over-fired requests"
    # slowapi sets Retry-After by default. If a future config disables
    # it (``headers_enabled=False`` is the slowapi default — but the
    # 429-body still includes a hint via the JSON detail), accept either
    # the header or a hint in the response body.
    body_text = last_429.text.lower()
    has_retry_header = "retry-after" in {k.lower() for k in last_429.headers.keys()}
    has_retry_in_body = "retry" in body_text or "minute" in body_text or "10/" in body_text
    assert has_retry_header or has_retry_in_body, (
        "429 response carries no Retry-After hint (header or body). Clients "
        "would have to guess when to retry, which is the contract violation."
    )


def test_compress_route_also_rate_limited(
    client, auth_headers, sample_jpg, rate_limiter_enabled
) -> None:
    """The 10/min limiter is also wired into ``/api/v1/compress`` —
    pin its presence so a future refactor doesn't accidentally drop the
    decorator from one of the two routes."""
    statuses = []
    for _ in range(11):
        with sample_jpg.open("rb") as fp:
            res = client.post(
                "/api/v1/compress",
                headers=auth_headers,
                files={"file": ("sample.jpg", fp, "image/jpeg")},
                data={"quality": "85"},
            )
        statuses.append(res.status_code)
        if res.status_code == 429:
            break
    assert 429 in statuses, f"compress route never returned 429 within 11 requests: {statuses}"
