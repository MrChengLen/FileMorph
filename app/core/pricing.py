# SPDX-License-Identifier: AGPL-3.0-or-later
"""Centralised, deployment-agnostic pricing/plan display source.

Two design goals:

1. **No drift.** Every limit number shown on /pricing is derived from
   ``app/core/quotas.py::QUOTAS`` — the same dict the runtime enforces. The
   page can never advertise a limit the server doesn't honour.
2. **Deployment-agnostic.** Displayed prices come from ``settings`` (env-vars),
   empty by default. A self-hoster who turns ``PRICING_PAGE_ENABLED`` on
   without setting prices sees the tiers *without* an amount — they do not
   inherit filemorph.io's prices. The Stripe price IDs (``stripe_*_price_id``)
   remain the source of truth for the actual charge; these strings are
   display-only.

Number formatting (``25,000`` vs ``25.000``) is locale-aware via Babel so the
DE and EN pages each read naturally; callers pass the active request locale.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.core.quotas import get_quota


@dataclass(frozen=True)
class SaasPlan:
    """One hosted-SaaS plan as the pricing page needs to render it."""

    tier: str
    price_display: str  # plain number ("3") or "" when not configured / free
    is_free: bool
    max_file_size_mb: int
    max_files_per_batch: int
    api_calls_per_month: int | None
    api_calls_display: str  # locale-formatted, e.g. "25,000" / "25.000"
    concurrency: int
    storage_days: int | None


@dataclass(frozen=True)
class CompliancePlan:
    """One Compliance-Edition (commercial license) tier."""

    key: str  # "starter" | "standard" | "enterprise"
    price_display: str  # plain number ("990") or "" when not configured
    is_from: bool  # render "from €24,900" when True


def _fmt(n: int, locale: str) -> str:
    """Locale-aware thousands grouping with a safe fallback."""
    try:
        from babel.numbers import format_decimal

        return format_decimal(n, locale=locale)
    except Exception:
        return f"{n:,}"


def _mb(num_bytes: int) -> int:
    return num_bytes // (1024 * 1024)


def _saas_plan(tier: str, price_display: str, locale: str) -> SaasPlan:
    q = get_quota(tier)
    return SaasPlan(
        tier=tier,
        price_display=price_display,
        is_free=(tier in ("anonymous", "free")),
        max_file_size_mb=_mb(q.max_file_size_bytes),
        max_files_per_batch=q.max_files_per_batch,
        api_calls_per_month=q.api_calls_per_month,
        api_calls_display=_fmt(q.api_calls_per_month or 0, locale),
        concurrency=q.concurrency,
        storage_days=q.storage_days,
    )


def anonymous_plan(locale: str = "en") -> SaasPlan:
    """The no-account tier (shown as a one-liner, not a card)."""
    return _saas_plan("anonymous", "0", locale)


def saas_plans(locale: str = "en") -> list[SaasPlan]:
    """Free / Pro / Business, in display order. Free is always €0; Pro and
    Business read their display price from settings (empty ⇒ no price)."""
    return [
        _saas_plan("free", "0", locale),
        _saas_plan("pro", settings.price_pro_display, locale),
        _saas_plan("business", settings.price_business_display, locale),
    ]


def compliance_plans(locale: str = "en") -> list[CompliancePlan]:
    """Compliance Edition tiers, in display order."""
    return [
        CompliancePlan("starter", settings.price_compliance_starter_display, is_from=False),
        CompliancePlan("standard", settings.price_compliance_standard_display, is_from=False),
        CompliancePlan("enterprise", settings.price_compliance_enterprise_display, is_from=True),
    ]


def saas_prices_configured() -> bool:
    """True when at least one paid SaaS price is set — drives whether the page
    shows amounts or a "Contact us" placeholder (self-host default: off)."""
    return bool(settings.price_pro_display or settings.price_business_display)


def price_currency() -> str:
    return settings.price_currency
