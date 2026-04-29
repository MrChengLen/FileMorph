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

    `max_file_size_bytes`, `max_files_per_batch`, and `output_cap_bytes` are
    enforced at runtime. Other fields are informational (used for UI display /
    future enforcement).

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


QUOTAS: dict[str, TierQuota] = {
    "anonymous": TierQuota(
        conversions_per_day=None,
        storage_days=None,
        api_calls_per_month=0,
        max_file_size_bytes=20 * _MB,
        max_files_per_batch=1,
        output_cap_bytes=60 * _MB,
    ),
    "free": TierQuota(
        conversions_per_day=None,
        storage_days=1,
        api_calls_per_month=500,
        max_file_size_bytes=50 * _MB,
        max_files_per_batch=5,
        output_cap_bytes=150 * _MB,
    ),
    "pro": TierQuota(
        conversions_per_day=None,
        storage_days=7,
        api_calls_per_month=10_000,
        max_file_size_bytes=100 * _MB,
        max_files_per_batch=25,
        output_cap_bytes=300 * _MB,
    ),
    "business": TierQuota(
        conversions_per_day=None,
        storage_days=30,
        api_calls_per_month=100_000,
        max_file_size_bytes=500 * _MB,
        max_files_per_batch=100,
        output_cap_bytes=500 * _MB,
    ),
    "enterprise": TierQuota(
        conversions_per_day=None,
        storage_days=None,
        api_calls_per_month=None,
        max_file_size_bytes=500 * _MB,
        max_files_per_batch=250,
        output_cap_bytes=500 * _MB,
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
