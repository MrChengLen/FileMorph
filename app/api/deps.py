# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.quotas import tier_for
from app.core.rate_limit import reject_failed_api_key
from app.core.security import find_active_api_key, validate_api_key
from app.db.base import get_db
from app.db.models import User


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


def caller_tier(request: Request, user: User | None) -> str:
    """The quota tier a convert/compress/PDF request runs on.

    An account (JWT or dashboard key) brings its own tier. Without one, a key
    from the key file gets ``API_KEYS_FILE_TIER`` — on a Community Edition
    instance, which has no accounts, the only way above anonymous. Everyone
    else is anonymous.

    The AI routes stay on ``tier_for(user)``: they are a paid add-on whose
    credit ledger needs an account, so a key-file tier must not unlock them.
    """
    if user is not None:
        return tier_for(user)
    if settings.api_keys_file_tier != "anonymous":
        key = request.headers.get("X-API-Key")
        if key and validate_api_key(key):
            return settings.api_keys_file_tier
    return "anonymous"
