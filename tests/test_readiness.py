# SPDX-License-Identifier: AGPL-3.0-or-later
"""S1-D readiness probe. /health stays the cheap liveness check; /ready
is the one an orchestrator should gate traffic on, because it exercises
the dependencies a real request needs (DB + writable tempdir)."""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock


def test_health_stays_cheap_and_simple(client):
    """/health is liveness: no dependency checks, never a false-negative
    that would cause an orchestrator to restart a healthy pod — and it
    leaks nothing (no version, no codec availability) on this
    unauthenticated endpoint (PT-011)."""
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_returns_ok_when_no_db_configured(client):
    """Community Edition has no DATABASE_URL; DB check is reported as
    ``skipped`` and readiness still succeeds."""
    r = client.get("/api/v1/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "skipped"
    assert body["checks"]["tempdir"] == "ok"


def test_ready_returns_503_when_db_ping_fails(client, monkeypatch):
    """If a DB is configured but unreachable (network blip, credentials,
    cluster restart), /ready must fail so the load balancer pulls this
    instance out of rotation until the DB comes back."""
    from app.api.routes import health

    fake_engine = MagicMock()

    @asynccontextmanager
    async def _broken_connect():
        raise ConnectionError("simulated DB outage")
        yield  # unreachable, satisfies async-gen protocol

    fake_engine.connect = _broken_connect
    monkeypatch.setattr(health, "engine", fake_engine)

    r = client.get("/api/v1/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "unreachable"
    # Tempdir probe still runs and is independent of DB state.
    assert body["checks"]["tempdir"] == "ok"
