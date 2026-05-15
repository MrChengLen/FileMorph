# SPDX-License-Identifier: AGPL-3.0-or-later
import logging
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.rate_limit import limiter
from app.db.base import engine
from app.models.schemas import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["System"])
@limiter.limit("30/minute")
async def health_check(request: Request) -> HealthResponse:
    """Liveness probe — the process is up and the framework is responding.
    Deliberately cheap: no DB or disk I/O, no dependency checks. Use /ready
    for the full dependency check.

    Returns only ``{"status": "ok"}``. The app version and codec
    availability are intentionally not exposed on this unauthenticated
    endpoint (pentest finding PT-011); operators read the running version
    from the deployed image tag / release."""
    return HealthResponse(status="ok")


@router.get("/ready", tags=["System"])
@limiter.limit("30/minute")
async def readiness_check(request: Request) -> JSONResponse:
    """Readiness probe — the app is ready to serve real traffic.

    Fails (HTTP 503) if:
      * a configured database is unreachable, or
      * the tempdir is not writable (no conversions possible without it).

    When no DB is configured (Community Edition), the DB check is reported
    as ``skipped`` and does not fail readiness."""
    checks: dict[str, str] = {}
    healthy = True

    if engine is None:
        checks["database"] = "skipped"
    else:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            logger.warning("Readiness DB-ping failed: %s", exc)
            checks["database"] = "unreachable"
            healthy = False

    probe_path = Path(tempfile.gettempdir()) / f"fm_ready_{uuid.uuid4().hex}"
    try:
        probe_path.write_bytes(b"ready")
        checks["tempdir"] = "ok"
    except Exception as exc:
        logger.warning("Readiness tempdir-write failed: %s", exc)
        checks["tempdir"] = "unwritable"
        healthy = False
    finally:
        try:
            os.unlink(probe_path)
        except OSError:
            pass

    payload = ReadinessResponse(
        status="ready" if healthy else "not_ready",
        checks=checks,
    ).model_dump()
    return JSONResponse(payload, status_code=200 if healthy else 503)
