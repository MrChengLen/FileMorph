# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shared slowapi limiter, plus the budget for failed API-key attempts.

Every limit is per route, set by an explicit ``@limiter.limit(...)`` on the
route, and counted per client IP — or per account on routes that need a
signed-in user (``key_func=account_or_ip``). No ``SlowAPIMiddleware`` is
installed, so a route without a decorator is not limited at all — which is
why there are no ``default_limits`` here: without the middleware slowapi
never applies them (they used to say 60/minute and limited nothing). A
blanket default via the middleware would also throttle HTML pages for
offices behind one IP. ``key_style="endpoint"`` counts per route, not per
URL, so ``DELETE /keys/<a>`` and ``DELETE /keys/<b>`` share one budget.
"""

import logging
import math
import time

from fastapi import HTTPException, Request, status
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.tokens import decode_token

limiter = Limiter(key_func=get_remote_address, key_style="endpoint")

# slowapi logs every exceeded limit at WARNING together with its key — a
# client IP or an account id. The privacy policy (§ 7) promises that the
# rate limiter's IPs never reach the logs; its errors still get through.
logging.getLogger("slowapi").setLevel(logging.ERROR)


def account_or_ip(request: Request) -> str:
    """Rate-limit key for routes behind ``get_current_user``: the account.

    Limits are checked after the dependencies, so the bearer token has
    already been verified by the time this runs; decoding it again is cheap.
    Counting per account means one user can't spend a budget for everyone
    behind the same IP — an office, or every visitor when the proxy doesn't
    forward client IPs. Falls back to the IP if there is no valid token.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            return "user:" + decode_token(auth.removeprefix("Bearer "), expected_type="access")
        except HTTPException:
            pass
    return get_remote_address(request)


# ``require_api_key`` (app/api/deps.py) is a dependency, and dependencies run
# before the route decorators check their limits — so a rejected key never
# reaches one. Failed attempts get their own per-IP budget instead, counted
# only after both key checks have failed: a valid key is never refused, so a
# client stuck on a revoked key can't lock out colleagues behind the same IP
# (or, when the proxy doesn't forward client IPs, every API user at once).
_FAILED_API_KEY_LIMIT = parse("30/minute")
_FAILED_API_KEY_SCOPE = "failed-api-key"


def reject_failed_api_key(request: Request) -> None:
    """Count one failed X-API-Key attempt; raise 429 once this IP is over budget.

    Returns normally while the IP is within budget — the caller then answers 401.
    """
    if not limiter.enabled:
        return
    ip = get_remote_address(request)
    if limiter.limiter.hit(_FAILED_API_KEY_LIMIT, ip, _FAILED_API_KEY_SCOPE):
        return
    reset_at, _ = limiter.limiter.get_window_stats(_FAILED_API_KEY_LIMIT, ip, _FAILED_API_KEY_SCOPE)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many invalid API key attempts. Try again later.",
        headers={"Retry-After": str(max(1, math.ceil(reset_at - time.time())))},
    )
