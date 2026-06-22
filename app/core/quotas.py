# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tier quota definitions for FileMorph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.db.models import User

_MB = 1024 * 1024


@dataclass(frozen=True)
class TierQuota:
    """Quota limits for a user tier.

    `max_file_size_bytes`, `max_files_per_batch`, `output_cap_bytes`, and
    `concurrency` are enforced at runtime (the first three here, `concurrency`
    via `app/core/concurrency.py`). Other fields are informational (used for UI
    display / future enforcement).

    `concurrency` is the per-actor parallel-request cap. It lives here so a
    tier is described by a single record (the pricing page, the monthly-quota
    gate, and the concurrency semaphore all read the same source — no drift).
    The **global** parallel cap (`settings.max_global_concurrency`, default 4
    on a 4 GB host) is the real backstop; a high per-tier value only raises the
    ceiling a single actor may request, never beyond the global cap.

    `output_cap_bytes` protects against bandwidth-amplification abuse: a 3 MB
    JPG re-encoded to PNG can balloon to 25 MB, and MP3→WAV is ~11×. The cap
    triggers after conversion, before the response is streamed.

    Values are sized to the production server's RAM headroom (a 4 GB server).
    Output is buffered in memory via `read_bytes()` before streaming, so cap
    × concurrent-requests must fit under available RAM after encoder peaks.
    Lower tiers get 3× amplification headroom; business/enterprise match the
    input cap because a 1500 MB buffer × 3 concurrent requests would OOM.
    Raising these caps is gated on S3 (StreamingResponse) or a bigger box.
    """

    conversions_per_day: Optional[int]
    storage_days: Optional[int]
    api_calls_per_month: Optional[int]
    max_file_size_bytes: int
    max_files_per_batch: int
    output_cap_bytes: int
    concurrency: int
    # Monthly included AI credits (Enterprise-Edition AI add-on). 0 = no AI
    # (free/anonymous — AI is paid-only); None = unlimited (enterprise). This
    # is an included-allotment LIMIT, not a price — the euro value of a credit
    # and the provider cost live in deployment env, never here.
    ai_credits_per_month: Optional[int]


# Pricing-overhaul 2026-05-25: the free/anonymous limits are deliberately
# generous (a market-undercut lever — most hosted converters cap free uploads
# far lower), and the paid SaaS tiers were re-priced to €3 (Pro) / €9 (Business)
# in the pricing config. Limit numbers here are the single source the pricing
# page reads (via app/core/pricing.py) so display never drifts from enforcement.
# Output caps stay ≤ 500 MB so the worst case (global cap of 4 concurrent ×
# 500 MB ≈ 2 GB buffered) fits the 4 GB host — raising the free/pro caps does
# not raise that ceiling because business already sets the 500 MB maximum.
QUOTAS: dict[str, TierQuota] = {
    "anonymous": TierQuota(
        conversions_per_day=None,
        storage_days=None,
        api_calls_per_month=0,
        max_file_size_bytes=30 * _MB,
        max_files_per_batch=1,
        output_cap_bytes=90 * _MB,
        concurrency=1,
        ai_credits_per_month=0,
    ),
    "free": TierQuota(
        conversions_per_day=None,
        storage_days=1,
        api_calls_per_month=1_000,
        max_file_size_bytes=100 * _MB,
        max_files_per_batch=10,
        output_cap_bytes=300 * _MB,
        concurrency=1,
        ai_credits_per_month=0,
    ),
    "pro": TierQuota(
        conversions_per_day=None,
        storage_days=7,
        api_calls_per_month=25_000,
        max_file_size_bytes=250 * _MB,
        max_files_per_batch=50,
        output_cap_bytes=400 * _MB,
        concurrency=3,
        ai_credits_per_month=200,
    ),
    "business": TierQuota(
        conversions_per_day=None,
        storage_days=30,
        api_calls_per_month=200_000,
        max_file_size_bytes=500 * _MB,
        max_files_per_batch=150,
        output_cap_bytes=500 * _MB,
        concurrency=6,
        ai_credits_per_month=1000,
    ),
    "enterprise": TierQuota(
        conversions_per_day=None,
        storage_days=None,
        api_calls_per_month=None,
        max_file_size_bytes=500 * _MB,
        max_files_per_batch=250,
        output_cap_bytes=500 * _MB,
        concurrency=10,
        ai_credits_per_month=None,
    ),
}


def get_quota(tier: str) -> TierQuota:
    """Return the TierQuota for the given tier name.

    Falls back to the 'anonymous' quota if the tier is unknown.
    """
    return QUOTAS.get(tier, QUOTAS["anonymous"])


def tier_for(user: "User | None") -> str:
    """Return the tier string for a User (or 'anonymous' if None)."""
    if user is None:
        return "anonymous"
    return user.tier.value
