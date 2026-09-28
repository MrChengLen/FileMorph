# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import reject_failed_api_key
from app.core.security import find_active_api_key, validate_api_key
from app.db.base import get_db


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    db: AsyncSession | None = Depends(get_db),
) -> str | None:
    """Validate X-API-Key if provided; allow through if absent (web UI public access).

    Accepts a file-store key (self-host/CLI) or, when a database is configured,
    an active dashboard-minted key — the same rule ``get_optional_user`` uses
    to resolve the key to its owner. A rejected key costs one of the caller's
    per-IP failed attempts; past the budget the answer is 429 instead of 401
    (``app/core/rate_limit.py``). A valid key always passes.
    """
    if x_api_key is None:
        return None
    if validate_api_key(x_api_key):
        return x_api_key
    if db is not None and await find_active_api_key(db, x_api_key):
        return x_api_key
    reject_failed_api_key(request)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key.",
    )
