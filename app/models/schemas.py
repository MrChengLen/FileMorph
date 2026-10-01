# SPDX-License-Identifier: AGPL-3.0-or-later
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


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


def _utc_today() -> date:
    """Today's date in UTC — a function of its own so tests can pin it."""
    return datetime.now(timezone.utc).date()


def _clean_reason(text: str) -> str:
    """Line breaks to ``\\n``, tabs to spaces, then drop every control (Cc)
    and format (Cf) character but ``\\n`` — bidi overrides and zero-width
    characters can make text read differently than it is — and trim."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    return "".join(
        ch for ch in text if ch == "\n" or unicodedata.category(ch) not in ("Cc", "Cf")
    ).strip()


class CancellationRequest(BaseModel):
    """Body schema for POST /billing/cancellation — the § 312k BGB
    cancellation form, submitted without login.

    ``email`` identifies the account; the confirmation goes to the address
    stored on it (or, without an account, to this one). The validator
    normalises the declaration so every consumer sees one shape: ``reason``
    only survives an extraordinary cancellation (cleaned by
    ``_clean_reason``), ``end_date`` only ``end == "date"``, where it is
    required and must not lie before yesterday (UTC) — the earliest date
    that is still "today" somewhere, so a visitor behind UTC can pick their
    own today.
    """

    email: EmailStr
    contract: Literal["pro", "business"]
    kind: Literal["ordinary", "extraordinary"]
    reason: str = Field("", max_length=1000)
    end: Literal["earliest", "date"]
    end_date: date | None = None
    # Honeypot. NOT enforced by the schema: a 422 would tell a bot it was
    # caught — and would turn away a real cancellation whose hidden field a
    # password manager filled. The route handles a filled one (see there).
    website: str = Field("", max_length=200)

    @model_validator(mode="after")
    def _normalise(self) -> "CancellationRequest":
        self.reason = _clean_reason(self.reason) if self.kind == "extraordinary" else ""
        if self.end == "earliest":
            self.end_date = None
        elif self.end_date is None:
            raise ValueError("end_date is required when end is 'date'.")
        elif self.end_date < _utc_today() - timedelta(days=1):
            raise ValueError("end_date must not be in the past.")
        return self
