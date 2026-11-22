# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end credit-limit path of the AI apply route (402).

The happy-path route tests run anonymous (no ledger). This exercises the branch
the audit flagged as untested: an authenticated paid user who has exhausted the
monthly credit allotment must get 402 — and a fresh user below the limit must get
through and have exactly one charge recorded. Database: the shared Cloud
test database (``cloud_db``, tests/support/db.py), emptied before every test.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.api.routes.auth import get_optional_user
from app.core import ai_credits as ai_credits_module
from app.core.auth import hash_password
from app.core.config import settings
from app.core.quotas import get_quota
from app.db.models import AiUsageRecord, TierEnum, User
from app.main import app
from tests.support.db import TestSession, cloud_db

PII_NOTE = b"Kontakt: max.mustermann@beispiel.de, IBAN DE89 3704 0044 0532 0130 00."
_AUTH_HEADERS = {"X-API-Key": "test-api-key-filemorph-ci"}

_db = cloud_db(ai_credits_module, override_get_db=False)


@pytest.fixture(scope="module", autouse=True)
def _install():
    saved = {k: settings.__dict__.get(k) for k in ("ai_operations_enabled", "ai_eligible_tiers")}
    settings.__dict__.update(
        ai_operations_enabled=True, ai_eligible_tiers="pro,business,enterprise"
    )
    yield
    settings.__dict__.update(saved)


@pytest.fixture(autouse=True)
def _drop_user_override():
    yield
    app.dependency_overrides.pop(get_optional_user, None)


async def _make_user(*, email: str, tier: TierEnum) -> User:
    async with TestSession() as s:
        user = User(email=email, password_hash=hash_password("pw-secure-1"), tier=tier)
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _seed(user_id: uuid.UUID, credits_each: int, n: int) -> None:
    async with TestSession() as s:
        for _ in range(n):
            s.add(AiUsageRecord(user_id=user_id, operation="redact", credits_charged=credits_each))
        await s.commit()


def _override_user(user: User):
    async def _o():
        return user

    return _o


def test_apply_402_when_credits_exhausted(client):
    user = asyncio.run(_make_user(email="exhausted@example.com", tier=TierEnum.pro))
    allot = get_quota("pro").ai_credits_per_month
    asyncio.run(_seed(user.id, 1, allot))  # fully consumed
    app.dependency_overrides[get_optional_user] = _override_user(user)
    resp = client.post(
        "/api/v1/ai/redact/apply",
        headers=_AUTH_HEADERS,
        files={"file": ("note.txt", PII_NOTE, "text/plain")},
    )
    assert resp.status_code == 402
    assert resp.headers.get("X-FileMorph-Error-Code") == "ai_credits_exhausted"


def test_apply_succeeds_below_limit_and_records_one_charge(client):
    user = asyncio.run(_make_user(email="fresh@example.com", tier=TierEnum.pro))
    app.dependency_overrides[get_optional_user] = _override_user(user)
    resp = client.post(
        "/api/v1/ai/redact/apply",
        headers=_AUTH_HEADERS,
        files={"file": ("note.txt", PII_NOTE, "text/plain")},
    )
    assert resp.status_code == 200, resp.text

    async def _used():
        from app.core.ai_credits import monthly_credits_used

        async with TestSession() as s:
            return await monthly_credits_used(s, user.id)

    assert asyncio.run(_used()) == settings.ai_credit_cost_redact  # exactly one op charged
