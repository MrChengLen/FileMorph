# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Prometheus instrumentation in app/core/observability.py.

The ``client`` fixture imports the app once with ``METRICS_ENABLED`` at
its default (true), so the endpoint is mounted and the counter is live.
Counters are process-global and accumulate across the session, so the
conversion tests assert deltas (after >= before + 1) rather than absolute
values. The disabled-path tests build a throwaway app / monkeypatch the
flag so they don't depend on the session app's wiring.
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import REGISTRY

from app.core import observability


def _counter(operation: str, src: str, tgt: str, status: str) -> float:
    val = REGISTRY.get_sample_value(
        "filemorph_conversions_total",
        {"operation": operation, "src": src, "tgt": tgt, "status": status},
    )
    return val or 0.0


def test_metrics_endpoint_exposes_prometheus_exposition(client):
    # One non-excluded request so the request-path families have at least
    # one sample regardless of test order (labelled metrics emit nothing
    # until first observed).
    client.get("/")
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "# HELP" in body
    assert "# TYPE" in body
    # Request-path metrics that power latency / error-rate dashboards.
    assert "http_request_duration_seconds" in body
    assert "http_requests_total" in body


def test_convert_increments_conversions_counter(client, auth_headers, sample_jpg):
    before = _counter("convert", "jpg", "png", "success")
    with sample_jpg.open("rb") as f:
        r = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert r.status_code == 200
    after = _counter("convert", "jpg", "png", "success")
    assert after >= before + 1


def test_convert_counter_visible_in_exposition(client, auth_headers, sample_jpg):
    with sample_jpg.open("rb") as f:
        client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    body = client.get("/api/v1/metrics").text
    assert (
        'filemorph_conversions_total{operation="convert",src="jpg",status="success",tgt="png"}'
        in body
    )


def test_unsupported_target_does_not_create_unbounded_series(client, auth_headers, sample_jpg):
    """An unsupported pair 422s before the counter site, so no series at
    all is created for the bogus target — and even if it were, the label
    would be capped (see bucket_format tests below)."""
    with sample_jpg.open("rb") as f:
        r = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "zzznotreal"},
        )
    assert r.status_code == 422
    assert _counter("convert", "zzznotreal", "zzznotreal", "failure") == 0.0


def test_bucket_format_caps_unknown_to_other():
    assert observability.bucket_format("jpg") == "jpg"
    assert observability.bucket_format("PNG") == "png"  # case-normalised
    assert observability.bucket_format("zzznotreal") == "other"
    assert observability.bucket_format("") == "other"
    assert observability.bucket_format(None) == "other"


def test_record_conversion_buckets_unknown_labels():
    before = _counter("convert", "other", "other", "success")
    observability.record_conversion("convert", "madeup1", "madeup2", "success")
    after = _counter("convert", "other", "other", "success")
    assert after == before + 1


def test_record_conversion_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(observability.settings, "metrics_enabled", False)
    before = _counter("compress", "png", "png", "success")
    observability.record_conversion("compress", "png", "png", "success")
    after = _counter("compress", "png", "png", "success")
    assert after == before


def test_setup_metrics_skipped_when_disabled(monkeypatch):
    """With METRICS_ENABLED=false the endpoint is never mounted, so a
    single-tenant self-hoster who doesn't run Prometheus pays nothing."""
    monkeypatch.setattr(observability.settings, "metrics_enabled", False)
    monkeypatch.setattr(observability, "_instrumented", False)
    throwaway = FastAPI()
    observability.setup_metrics(throwaway)
    paths = {getattr(route, "path", None) for route in throwaway.routes}
    assert "/api/v1/metrics" not in paths
