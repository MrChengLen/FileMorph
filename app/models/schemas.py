# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel


class HealthResponse(BaseModel):
    # Liveness only — no version or codec info on this unauthenticated
    # endpoint (PT-011). /ready carries operational state; the running
    # version is the deployed image tag.
    status: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


class FormatsResponse(BaseModel):
    conversions: dict[str, list[str]]
    compression: dict[str, list[str]]


class ErrorResponse(BaseModel):
    detail: str


class CheckoutRequest(BaseModel):
    """Body schema for POST /billing/checkout/{tier}.

    The user must explicitly waive their 14-day right of withdrawal under
    §312g BGB / §356(5) BGB before paid-tier API access can be activated
    immediately on Stripe checkout completion. Without this acknowledgement
    the request is rejected with HTTP 400 — the standard 14-day withdrawal
    protection then applies and immediate activation is deferred.
    """

    withdrawal_waiver_acknowledged: bool = False
