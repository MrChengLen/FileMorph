# SPDX-License-Identifier: AGPL-3.0-or-later
"""§ 312k BGB online cancellation — ``POST /api/v1/billing/cancellation``.

A consumer cancels without logging in: the email address identifies the
account and receives the confirmation. These tests pin

* the gate (503 without Stripe) and every 422;
* the automatic path — exactly one live subscription of the named plan →
  ``cancel_at_period_end`` in Stripe, a confirmation with the end date, no
  operator mail;
* every manual path (no or ambiguous account, extraordinary, specific date,
  no / several / another subscription, Stripe error) → confirmation plus
  operator mail, nothing changed in Stripe;
* a filled honeypot → operator mail only (suspected spam, maybe a password
  manager), no confirmation, ``email_sent: false``;
* no account enumeration (same answer either way), no plain address or
  reason in the audit chain or the logs, the confirmation's language, and
  the 10/hour limit.

Stripe is mocked at the SDK boundary with real ``StripeObject``s, so the
helper in ``app/core/billing.py`` runs for real: in the pinned SDK such an
object is no longer a dict, which a bare MagicMock would hide.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import stripe
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import billing as billing_module
from app.core import audit as audit_module
from app.core import billing as billing_core
from app.core import email as email_module
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.base import Base, get_db
from app.db.models import AuditEvent, TierEnum, User
from app.main import app
from app.models import schemas as schemas_module
from app.models.schemas import CancellationRequest

URL = "/api/v1/billing/cancellation"
PRO_PRICE = "price_test_pro"
BUSINESS_PRICE = "price_test_business"
OPERATOR = "ops@operator.example"
CUSTOMER = "kunde.privat@example.com"
PERIOD_END = 1_800_000_000  # 2027-01-15T08:00:00Z — on the subscription item
CANCEL_AT = 1_801_000_000  # 2027-01-26T21:46:40Z — what modify() reports
LEGACY_PERIOD_END = 1_802_000_000  # 2027-02-07T11:33:20Z — pre-2025 top-level field
WITHHELD = "given in the form, not repeated in this email"
FROZEN_TODAY = date(2026, 9, 30)


@pytest.fixture
def frozen_today(monkeypatch):
    """Pin the UTC date the schema checks ``end_date`` against, so the
    boundary tests can't flake when the date rolls over mid-test."""
    monkeypatch.setattr(schemas_module, "_utc_today", lambda: FROZEN_TODAY)
    return FROZEN_TODAY


@pytest.fixture
def rate_limiter_enabled():
    """Flip the shared slowapi limiter ON for one test, fresh storage, always
    OFF again on teardown — a local copy of the fixture of the same name in
    tests/test_rate_limit_routes.py."""
    limiter.enabled = True
    if hasattr(limiter, "reset"):
        limiter.reset()
    elif hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
        limiter._storage.reset()
    try:
        yield
    finally:
        limiter.enabled = False


# ── Test database (mirrors tests/test_rate_limit_routes.py) ─────────────────

_test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False, class_=AsyncSession)


async def _setup_schema() -> None:
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _wipe() -> None:
    async with _TestSession() as s:
        await s.execute(delete(AuditEvent))
        await s.execute(delete(User))
        await s.commit()


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    asyncio.run(_setup_schema())
    app.dependency_overrides[get_db] = _override_get_db
    original_audit = audit_module.AsyncSessionLocal
    audit_module.AsyncSessionLocal = _TestSession
    yield
    audit_module.AsyncSessionLocal = original_audit
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    """Stripe, SMTP and the operator inbox configured; monkeypatch puts every
    value back after the test, also when it fails."""
    for key, value in {
        "stripe_secret_key": "sk_test_dummy",
        "stripe_pro_price_id": PRO_PRICE,
        "stripe_business_price_id": BUSINESS_PRICE,
        "smtp_host": "smtp.example.test",
        "contact_form_recipient_email": OPERATOR,
        "audit_fail_closed": False,
        "app_base_url": "http://localhost:8000",
    }.items():
        monkeypatch.setitem(settings.__dict__, key, value)


@pytest.fixture(autouse=True)
def _wipe_between_tests():
    asyncio.run(_wipe())
    yield


@pytest.fixture(autouse=True)
def send_mock(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr(email_module, "send_email", fake)
    return fake


@pytest.fixture(autouse=True)
def stripe_api(monkeypatch):
    """``stripe.Subscription.list`` / ``.modify`` — never the network. By
    default the customer has no subscriptions; tests set return values."""
    api = SimpleNamespace(list=MagicMock(return_value=_stripe_list()), modify=MagicMock())
    monkeypatch.setattr(stripe.Subscription, "list", api.list)
    monkeypatch.setattr(stripe.Subscription, "modify", api.modify)
    return api


# ── Helpers ──────────────────────────────────────────────────────────────────


def _subscription(
    sub_id: str = "sub_1",
    *,
    status: str = "active",
    price: str = PRO_PRICE,
    item_period_end: int | None = PERIOD_END,
    **extra,
) -> dict:
    item = {"id": f"si_{sub_id}", "object": "subscription_item", "price": {"id": price}}
    if item_period_end is not None:
        item["current_period_end"] = item_period_end
    return {
        "id": sub_id,
        "object": "subscription",
        "status": status,
        "items": {"object": "list", "data": [item]},
        **extra,
    }


def _stripe_list(*subs: dict):
    return stripe.ListObject.construct_from({"object": "list", "data": list(subs)}, "sk_test")


def _stripe_sub(sub: dict):
    return stripe.Subscription.construct_from(sub, "sk_test")


def _one_live_pro_subscription(stripe_api, **modified) -> None:
    """The automatic case: one active Pro subscription; modify() answers
    with ``cancel_at`` set, unless ``modified`` says otherwise."""
    stripe_api.list.return_value = _stripe_list(_subscription())
    stripe_api.modify.return_value = _stripe_sub(
        _subscription(cancel_at_period_end=True, **({"cancel_at": CANCEL_AT} | modified))
    )


async def _insert_user(
    *,
    email: str = CUSTOMER,
    tier: TierEnum = TierEnum.pro,
    stripe_customer_id: str | None = "cus_test",
    preferred_lang: str | None = None,
    deleted: bool = False,
) -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash="never-checked-here",
            tier=tier,
            stripe_customer_id=stripe_customer_id,
            preferred_lang=preferred_lang,
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _events(event_type: str | None = None) -> list[AuditEvent]:
    async def _q():
        async with _TestSession() as s:
            stmt = select(AuditEvent).order_by(AuditEvent.id.asc())
            if event_type is not None:
                stmt = stmt.where(AuditEvent.event_type == event_type)
            return list((await s.execute(stmt)).scalars().all())

    return asyncio.run(_q())


def _payload(event_type: str) -> dict:
    rows = _events(event_type)
    assert len(rows) == 1, f"expected one {event_type} event, got {len(rows)}"
    return json.loads(rows[0].payload_json)


def _today_utc():
    return datetime.now(timezone.utc).date()


def _form(**overrides) -> dict:
    body = {
        "email": CUSTOMER,
        "contract": "pro",
        "kind": "ordinary",
        "reason": "",
        "end": "earliest",
        "end_date": None,
        "website": "",
    }
    body.update(overrides)
    return body


def _post(client, body: dict | None = None, *, lang: str = "en"):
    return client.post(f"{URL}?lang={lang}", json=_form() if body is None else body)


def _mails(send_mock) -> list[dict]:
    return [c.kwargs for c in send_mock.await_args_list]


def _confirmation(send_mock, to: str = CUSTOMER) -> dict:
    sent = [m for m in _mails(send_mock) if m["to"] == to]
    assert len(sent) == 1, f"expected one confirmation to {to}, got {len(sent)}"
    return sent[0]


def _operator_mails(send_mock) -> list[dict]:
    return [m for m in _mails(send_mock) if m["to"] == OPERATOR]


def _assert_received_ok(res, *, email_sent: bool = True) -> None:
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"received_at", "email_sent"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["received_at"])
    assert body["email_sent"] is email_sent


# ── Gate, honeypot, validation ───────────────────────────────────────────────


def test_503_when_stripe_is_not_configured(client, monkeypatch, send_mock, stripe_api):
    monkeypatch.setitem(settings.__dict__, "stripe_secret_key", "")
    res = _post(client)
    assert res.status_code == 503
    assert res.json() == {"detail": "Billing not configured."}
    send_mock.assert_not_awaited()
    stripe_api.list.assert_not_called()
    assert _events() == []


async def _no_database():
    yield None  # what get_db yields without DATABASE_URL


def test_503_without_a_database(client, monkeypatch, send_mock, stripe_api):
    monkeypatch.setitem(app.dependency_overrides, get_db, _no_database)
    res = _post(client)
    assert res.status_code == 503
    assert res.json() == {"detail": "Billing not configured."}
    send_mock.assert_not_awaited()
    stripe_api.list.assert_not_called()
    assert _events() == []


@pytest.mark.parametrize("matched", [True, False], ids=["known-address", "unknown-address"])
def test_filled_honeypot_goes_to_the_operator_without_confirmation(
    client, send_mock, stripe_api, matched
):
    """A password manager may autofill the hidden field on a real
    cancellation, so a filled honeypot is not dropped: it is received and
    handed to the operator as suspected spam. Nothing goes to Stripe and
    nothing to the entered address — bots still can't use the form as a mail
    relay — and the answer admits that no confirmation was sent."""
    user = asyncio.run(_insert_user()) if matched else None
    _one_live_pro_subscription(stripe_api)

    res = _post(client, _form(website="http://spam.example/cheap"))
    _assert_received_ok(res, email_sent=False)

    stripe_api.list.assert_not_called()
    stripe_api.modify.assert_not_called()
    [operator] = _mails(send_mock)  # the only mail — none to the entered address
    assert operator["to"] == OPERATOR
    assert operator["reply_to"] == CUSTOMER
    assert operator["subject"] == "[FileMorph Kündigung] Bitte manuell bearbeiten"
    assert "Warum manuell: Spam-Verdacht" in operator["text"]
    assert "Passwort-Manager" in operator["text"]
    assert "Bestätigung an Kunden: NICHT versendet (Spam-Verdacht)" in operator["text"]
    assert "Zu tun:" not in operator["text"]  # the Spam-Verdacht line says what to do
    account = f"Konto: gefunden (ID {user.id}" if matched else "Konto: nicht gefunden"
    assert account in operator["text"]

    received = _events("billing.cancellation.received")
    assert len(received) == 1
    assert received[0].actor_user_id == (user.id if matched else None)
    assert json.loads(received[0].payload_json)["matched"] is matched
    assert _payload("billing.cancellation.manual_review") == {"reason": "honeypot"}
    assert _events("billing.cancellation.scheduled") == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"contract": "enterprise"},
        {"kind": "whenever"},
        {"end": "tomorrow"},
        {"end": "date"},  # end_date missing
        {"end": "date", "end_date": "2020-01-01"},  # in the past
        {"kind": "extraordinary", "reason": "x" * 1001},
    ],
    ids=[
        "bad-email",
        "bad-contract",
        "bad-kind",
        "bad-end",
        "date-missing",
        "past-date",
        "long-reason",
    ],
)
def test_invalid_body_is_422_and_does_nothing(client, send_mock, stripe_api, overrides):
    res = _post(client, _form(**overrides))
    assert res.status_code == 422, res.text
    send_mock.assert_not_awaited()
    stripe_api.list.assert_not_called()
    assert _events() == []


def test_missing_email_is_422(client, send_mock):
    body = _form()
    del body["email"]
    assert _post(client, body).status_code == 422
    send_mock.assert_not_awaited()


def _reason(text: str) -> str:
    return CancellationRequest(
        email=CUSTOMER, contract="pro", kind="extraordinary", end="earliest", reason=text
    ).reason


@pytest.mark.parametrize(
    "char",
    ["\u202e", "\u2066", "\u200b", "\ufeff", "\x07", "\x00", "\x1b"],
    ids=["rtl-override", "ltr-isolate", "zero-width-space", "bom", "bell", "nul", "escape"],
)
def test_reason_drops_invisible_and_control_characters(char):
    """Bidi overrides and zero-width characters can make the reason read
    differently than it is; control characters have no place in it."""
    assert _reason(f"Um{char}zug ins Ausland") == "Umzug ins Ausland"


def test_reason_normalises_line_breaks_and_tabs():
    assert _reason("\t Zeile 1\r\nZeile 2\rZeile\t3 \n") == "Zeile 1\nZeile 2\nZeile 3"


@pytest.mark.parametrize("days_back", [0, 1], ids=["today-utc", "yesterday-utc"])
def test_end_date_from_yesterday_utc_is_accepted(client, frozen_today, days_back):
    """UTC yesterday is still "today" for a visitor behind UTC (the Americas
    in the evening) — picking their own today must not be rejected."""
    wanted = (frozen_today - timedelta(days=days_back)).isoformat()
    res = _post(client, _form(end="date", end_date=wanted))
    _assert_received_ok(res)
    assert _payload("billing.cancellation.received")["end_date"] == wanted


def test_end_date_two_days_back_is_422(client, frozen_today, send_mock):
    wanted = (frozen_today - timedelta(days=2)).isoformat()
    res = _post(client, _form(end="date", end_date=wanted))
    assert res.status_code == 422, res.text
    send_mock.assert_not_awaited()
    assert _events() == []


def test_earliest_ignores_a_sent_end_date(client, stripe_api):
    """``end_date`` only counts for ``end: "date"`` — here the case stays
    automatic and the date is dropped everywhere."""
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    later = (_today_utc() + timedelta(days=40)).isoformat()
    res = _post(client, _form(end_date=later))
    _assert_received_ok(res)
    stripe_api.modify.assert_called_once()
    assert _payload("billing.cancellation.received")["end_date"] is None


# ── Unmatched address ────────────────────────────────────────────────────────


def test_unknown_address_confirms_and_mails_the_operator(client, send_mock, stripe_api):
    res = _post(client)
    _assert_received_ok(res)

    confirmation = _confirmation(send_mock)
    assert confirmation["reply_to"] == OPERATOR
    assert "We will process your cancellation" in confirmation["text"]
    assert CUSTOMER in confirmation["text"]

    [operator] = _operator_mails(send_mock)
    assert operator["subject"] == "[FileMorph Kündigung] Bitte manuell bearbeiten"
    assert operator["reply_to"] == CUSTOMER
    assert "Konto: nicht gefunden" in operator["text"]
    assert "Warum manuell: Kein Konto" in operator["text"]
    assert "Bestätigung an Kunden: versendet" in operator["text"]
    assert operator["html"].startswith("<pre")

    stripe_api.list.assert_not_called()
    received = _events("billing.cancellation.received")
    assert received[0].actor_user_id is None
    assert json.loads(received[0].payload_json)["matched"] is False
    assert _payload("billing.cancellation.manual_review") == {"reason": "no_account"}
    assert [row.actor_ip for row in _events()] == [None, None]  # no IPs in the audit log


def test_ordinary_cancellation_drops_the_reason(client, send_mock):
    res = _post(client, _form(reason="my very private reason"))
    _assert_received_ok(res)
    for mail in _mails(send_mock):
        assert "my very private reason" not in mail["text"]
        assert "my very private reason" not in mail["html"]


@pytest.mark.parametrize("accounts", [0, 2], ids=["unknown-address", "ambiguous-address"])
def test_reason_is_not_echoed_to_an_address_without_one_account(client, send_mock, accounts):
    """Free text from the form only goes back to one account's own mailbox —
    otherwise anyone could send their words to any address from our mail
    domain. The Reason row stays, with a fixed text; the operator gets it."""
    if accounts == 2:
        asyncio.run(_insert_user(email=CUSTOMER))
        asyncio.run(_insert_user(email=CUSTOMER.upper(), stripe_customer_id="cus_other"))
    spam = "Cheap pills at http://spam.example"
    _assert_received_ok(_post(client, _form(kind="extraordinary", reason=spam)))

    confirmation = _confirmation(send_mock)
    assert f"Reason: {WITHHELD}" in confirmation["text"]
    assert WITHHELD in confirmation["html"]
    assert "spam.example" not in confirmation["text"]
    assert "spam.example" not in confirmation["html"]
    [operator] = _operator_mails(send_mock)
    assert operator["text"].endswith(f"---\nGrund:\n{spam}\n")


# ── Automatic path ───────────────────────────────────────────────────────────


def test_automatic_cancellation_at_period_end(client, send_mock, stripe_api):
    user = asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)

    res = _post(client)
    _assert_received_ok(res)

    stripe_api.list.assert_called_once_with(customer="cus_test", status="all", limit=10)
    stripe_api.modify.assert_called_once_with("sub_1", cancel_at_period_end=True)

    [confirmation] = _mails(send_mock)  # no operator mail
    assert confirmation["to"] == CUSTOMER
    assert confirmation["subject"] == "We have received your FileMorph cancellation"
    assert "Your Pro subscription ends on 2027-01-26." in confirmation["text"]
    assert "2027-01-26" in confirmation["html"]
    assert "Ordinary cancellation" in confirmation["text"]
    assert "At the earliest possible date" in confirmation["text"]

    received = _events("billing.cancellation.received")[0]
    assert received.actor_user_id == user.id
    assert [row.actor_ip for row in _events()] == [None, None]  # no IPs in the audit log
    assert json.loads(received.payload_json) == {
        "email_hash": hashlib.sha256(CUSTOMER.encode()).hexdigest(),
        "contract": "pro",
        "kind": "ordinary",
        "end": "earliest",
        "end_date": None,
        "matched": True,
    }
    assert _payload("billing.cancellation.scheduled") == {"ends_at": "2027-01-26"}
    assert _events("billing.cancellation.manual_review") == []


def test_unknown_end_says_end_of_the_billing_period(client, send_mock, stripe_api):
    asyncio.run(_insert_user())
    stripe_api.list.return_value = _stripe_list(_subscription())
    stripe_api.modify.return_value = _stripe_sub(
        _subscription(cancel_at_period_end=True, item_period_end=None)
    )
    res = _post(client)
    _assert_received_ok(res)
    text = _confirmation(send_mock)["text"]
    assert "Your Pro subscription ends at the end of the current billing period." in text
    assert _payload("billing.cancellation.scheduled") == {"ends_at": None}
    assert _operator_mails(send_mock) == []


@pytest.mark.parametrize(
    "modified,expected",
    [
        (_subscription(cancel_at=CANCEL_AT), "2027-01-26"),
        (_subscription(cancel_at=None), "2027-01-15"),
        (_subscription(item_period_end=None, current_period_end=LEGACY_PERIOD_END), "2027-02-07"),
    ],
    ids=["cancel_at", "item-period-end", "legacy-period-end"],
)
def test_helper_reads_the_end_defensively(stripe_api, modified, expected):
    stripe_api.list.return_value = _stripe_list(_subscription())
    stripe_api.modify.return_value = _stripe_sub(modified)
    outcome = asyncio.run(billing_core.cancel_subscription_at_period_end("cus_x", PRO_PRICE))
    assert outcome.manual_reason is None
    assert outcome.ends_at.strftime("%Y-%m-%d") == expected


def test_helper_is_a_noop_without_a_stripe_key(monkeypatch, stripe_api):
    monkeypatch.setitem(settings.__dict__, "stripe_secret_key", "")
    outcome = asyncio.run(billing_core.cancel_subscription_at_period_end("cus_x", PRO_PRICE))
    assert outcome.manual_reason == "stripe_error"
    stripe_api.list.assert_not_called()


def test_match_is_case_insensitive_and_confirms_to_the_stored_address(
    client, send_mock, stripe_api
):
    """The confirmation goes to the address stored on the account, not the
    typed spelling: without a password, the owner's mailbox is the check."""
    user = asyncio.run(_insert_user(email="Mixed.Case@Example.com"))
    _one_live_pro_subscription(stripe_api)
    res = _post(client, _form(email="mixed.case@EXAMPLE.com"))
    _assert_received_ok(res)
    stripe_api.modify.assert_called_once()
    assert _events("billing.cancellation.received")[0].actor_user_id == user.id
    [confirmation] = _mails(send_mock)
    assert confirmation["to"] == "Mixed.Case@Example.com"
    assert "Account email: Mixed.Case@Example.com" in confirmation["text"]
    assert "mixed.case@example.com" not in confirmation["text"]


def test_underscore_is_not_a_wildcard(client, stripe_api):
    """``a_b@…`` must not match ``axb@…`` — ``ilike`` would treat ``_`` as a
    wildcard; the lookup compares lowercased strings instead."""
    asyncio.run(_insert_user(email="axb@example.com"))
    _one_live_pro_subscription(stripe_api)
    res = _post(client, _form(email="a_b@example.com"))
    _assert_received_ok(res)
    stripe_api.list.assert_not_called()
    assert _payload("billing.cancellation.manual_review") == {"reason": "no_account"}


# ── Manual paths ─────────────────────────────────────────────────────────────


def test_soft_deleted_account_is_not_matched(client, stripe_api):
    asyncio.run(_insert_user(deleted=True))
    _one_live_pro_subscription(stripe_api)
    res = _post(client)
    _assert_received_ok(res)
    stripe_api.list.assert_not_called()
    assert _events("billing.cancellation.received")[0].actor_user_id is None
    assert _payload("billing.cancellation.manual_review") == {"reason": "no_account"}


def test_two_accounts_differing_in_case_are_ambiguous(client, send_mock, stripe_api):
    asyncio.run(_insert_user(email="dup@example.com"))
    asyncio.run(_insert_user(email="DUP@example.com", stripe_customer_id="cus_other"))
    res = _post(client, _form(email="dup@example.com"))
    _assert_received_ok(res)
    stripe_api.list.assert_not_called()
    assert _payload("billing.cancellation.manual_review") == {"reason": "ambiguous_account"}
    assert "Konto: mehrdeutig" in _operator_mails(send_mock)[0]["text"]


def test_contract_mismatch_is_manual(client, send_mock, stripe_api):
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    res = _post(client, _form(contract="business"))
    _assert_received_ok(res)
    stripe_api.modify.assert_not_called()
    assert _payload("billing.cancellation.manual_review") == {"reason": "contract_mismatch"}
    assert "Contract: FileMorph Business" in _confirmation(send_mock)["text"]
    assert "We will process your cancellation" in _confirmation(send_mock)["text"]
    [operator] = _operator_mails(send_mock)
    assert "nicht der angegebene Vertrag" in operator["text"]


def test_extraordinary_never_calls_stripe_and_escapes_the_reason(client, send_mock, stripe_api):
    user = asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    reason = "<b>Umzug</b> ins Ausland"
    res = _post(client, _form(kind="extraordinary", reason=f"  {reason}\n"))
    _assert_received_ok(res)

    stripe_api.list.assert_not_called()
    stripe_api.modify.assert_not_called()

    confirmation = _confirmation(send_mock)
    assert "&lt;b&gt;Umzug&lt;/b&gt; ins Ausland" in confirmation["html"]
    assert "<b>Umzug</b>" not in confirmation["html"]
    assert f"Reason: {reason}" in confirmation["text"]  # one account's own mailbox
    assert WITHHELD not in confirmation["text"]
    assert "Extraordinary cancellation" in confirmation["text"]

    [operator] = _operator_mails(send_mock)
    assert operator["text"].endswith(f"---\nGrund:\n{reason}\n")
    assert "&lt;b&gt;Umzug&lt;/b&gt;" in operator["html"]
    assert f"ID {user.id}, Tarif pro" in operator["text"]

    assert _payload("billing.cancellation.manual_review") == {"reason": "extraordinary"}
    for row in _events():
        assert "Umzug" not in row.payload_json
        assert CUSTOMER not in row.payload_json


def test_specific_date_is_manual(client, send_mock, stripe_api):
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    wanted = (_today_utc() + timedelta(days=30)).isoformat()
    res = _post(client, _form(end="date", end_date=wanted))
    _assert_received_ok(res)
    stripe_api.list.assert_not_called()
    assert f"Requested end: On {wanted}" in _confirmation(send_mock)["text"]
    assert f"Gewünschtes Ende: zum {wanted}" in _operator_mails(send_mock)[0]["text"]
    assert _payload("billing.cancellation.manual_review") == {"reason": "specific_date"}
    assert _payload("billing.cancellation.received")["end_date"] == wanted


def test_multiple_live_subscriptions_are_manual(client, stripe_api):
    asyncio.run(_insert_user())
    stripe_api.list.return_value = _stripe_list(
        _subscription("sub_1"), _subscription("sub_2", status="past_due")
    )
    _assert_received_ok(_post(client))
    stripe_api.modify.assert_not_called()
    assert _payload("billing.cancellation.manual_review") == {"reason": "multiple_subscriptions"}


def test_only_ended_subscriptions_are_manual(client, stripe_api):
    asyncio.run(_insert_user())
    stripe_api.list.return_value = _stripe_list(
        _subscription("sub_1", status="canceled"),
        _subscription("sub_2", status="incomplete_expired"),
    )
    _assert_received_ok(_post(client))
    stripe_api.modify.assert_not_called()
    assert _payload("billing.cancellation.manual_review") == {"reason": "no_live_subscription"}


def test_account_without_stripe_customer_is_manual(client, stripe_api):
    asyncio.run(_insert_user(tier=TierEnum.free, stripe_customer_id=None))
    _assert_received_ok(_post(client))
    stripe_api.list.assert_not_called()
    assert _payload("billing.cancellation.manual_review") == {"reason": "no_live_subscription"}


@pytest.mark.parametrize("failing_call", ["list", "modify"])
def test_stripe_error_is_manual_and_still_200(client, send_mock, stripe_api, failing_call):
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    getattr(stripe_api, failing_call).side_effect = stripe.APIConnectionError(
        "secret-network-detail"
    )
    res = _post(client)
    _assert_received_ok(res)
    assert "secret-network-detail" not in res.text
    assert _payload("billing.cancellation.manual_review") == {"reason": "stripe_error"}
    assert _events("billing.cancellation.scheduled") == []
    assert "Stripe-Aufruf fehlgeschlagen" in _operator_mails(send_mock)[0]["text"]
    assert "We will process your cancellation" in _confirmation(send_mock)["text"]


def test_unexpected_error_in_the_stripe_step_is_manual_and_still_200(
    client, monkeypatch, send_mock
):
    """Not only StripeError: any failure in the Stripe step (here a KeyError
    from an odd response) must leave a received cancellation a 200."""
    asyncio.run(_insert_user())
    monkeypatch.setattr(
        billing_module,
        "cancel_subscription_at_period_end",
        AsyncMock(side_effect=KeyError("id")),
    )
    res = _post(client)
    _assert_received_ok(res)
    assert _payload("billing.cancellation.manual_review") == {"reason": "stripe_error"}
    assert "Stripe-Aufruf fehlgeschlagen" in _operator_mails(send_mock)[0]["text"]
    assert "We will process your cancellation" in _confirmation(send_mock)["text"]


# ── Email delivery ───────────────────────────────────────────────────────────


def test_failed_confirmation_is_reported_and_handed_to_the_operator(client, send_mock, stripe_api):
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    send_mock.side_effect = [email_module.EmailSendError("smtp down"), None]

    res = _post(client)
    _assert_received_ok(res, email_sent=False)

    stripe_api.modify.assert_called_once()  # the cancellation itself stands
    [operator] = _operator_mails(send_mock)
    assert "Bestätigung an Kunden: NICHT versendet" in operator["text"]
    assert "Automatisch erledigt" in operator["text"]
    assert "Vertragsende 2027-01-26" in operator["text"]
    assert _payload("billing.cancellation.scheduled") == {"ends_at": "2027-01-26"}


def test_confirmation_that_cannot_be_rendered_is_reported_and_handed_to_the_operator(
    client, monkeypatch, send_mock, stripe_api
):
    """E.g. a translation with a broken placeholder: the cancellation stands,
    the answer admits the missing mail, the operator is told to send it."""
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    monkeypatch.setattr(email_module, "render_email", MagicMock(side_effect=KeyError("tier_label")))
    res = _post(client)
    _assert_received_ok(res, email_sent=False)
    stripe_api.modify.assert_called_once()
    [operator] = _mails(send_mock)  # the confirmation never reached send_email
    assert operator["to"] == OPERATOR
    assert "Bestätigung an Kunden: NICHT versendet – bitte manuell nachholen" in operator["text"]
    assert "Automatisch erledigt" in operator["text"]


def test_without_smtp_email_sent_is_false(client, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "smtp_host", "")
    _assert_received_ok(_post(client), email_sent=False)


def test_failed_operator_mail_does_not_fail_the_request(client, send_mock):
    send_mock.side_effect = [None, email_module.EmailSendError("smtp down")]
    _assert_received_ok(_post(client))
    assert len(_operator_mails(send_mock)) == 1


def test_no_operator_address_still_confirms(client, monkeypatch, send_mock):
    for key in ("contact_form_recipient_email", "smtp_reply_to", "smtp_from_email"):
        monkeypatch.setitem(settings.__dict__, key, "")
    _assert_received_ok(_post(client))
    [confirmation] = _mails(send_mock)
    assert confirmation["to"] == CUSTOMER
    assert confirmation["reply_to"] is None
    assert "http://localhost:8000/contact" in confirmation["text"]


# ── No enumeration, locale, privacy ──────────────────────────────────────────


def test_same_answer_for_known_and_unknown_addresses(client, stripe_api):
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    known = _post(client)
    unknown = _post(client, _form(email="nobody@example.com"))
    assert known.status_code == unknown.status_code == 200
    assert set(known.json()) == set(unknown.json()) == {"received_at", "email_sent"}
    assert known.json()["email_sent"] is unknown.json()["email_sent"] is True


@pytest.mark.parametrize(
    "preferred_lang,request_lang,expected",
    [("en", "de", "en"), ("de", "en", "de"), (None, "en", "en")],
)
def test_matched_account_gets_its_preferred_language(
    client, send_mock, stripe_api, preferred_lang, request_lang, expected
):
    asyncio.run(_insert_user(preferred_lang=preferred_lang))
    _one_live_pro_subscription(stripe_api)
    _assert_received_ok(_post(client, lang=request_lang))
    assert f'<html lang="{expected}">' in _confirmation(send_mock)["html"]


@pytest.mark.parametrize("request_lang", ["en", "de"])
def test_unmatched_address_gets_the_request_language(client, send_mock, request_lang):
    _assert_received_ok(_post(client, lang=request_lang))
    assert f'<html lang="{request_lang}">' in _confirmation(send_mock)["html"]


def test_logs_never_carry_the_address(client, stripe_api, caplog):
    # INFO, the production level: at DEBUG, aiosqlite (test DB only) echoes
    # the SQL parameters of the lookup.
    caplog.set_level(logging.INFO)
    _post(client)  # unmatched
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    stripe_api.list.side_effect = stripe.APIConnectionError("down")
    _post(client)  # matched, Stripe error with traceback
    assert "example.com" in caplog.text  # the domain is fine …
    assert "kunde.privat" not in caplog.text  # … the local part is not


# ── Audit failures (AUDIT_FAIL_CLOSED) ───────────────────────────────────────


def test_outcome_audit_failure_does_not_fail_a_processed_cancellation(
    client, monkeypatch, send_mock, stripe_api
):
    monkeypatch.setitem(settings.__dict__, "audit_fail_closed", True)
    real_record = billing_module.record_event

    async def _record(event_type, **kwargs):
        if event_type != "billing.cancellation.received":
            raise audit_module.AuditWriteError("chain unavailable")
        await real_record(event_type, **kwargs)

    monkeypatch.setattr(billing_module, "record_event", _record)
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)

    _assert_received_ok(_post(client))
    stripe_api.modify.assert_called_once()
    assert "ends on 2027-01-26" in _confirmation(send_mock)["text"]


def test_receipt_audit_failure_fails_before_anything_happens(monkeypatch, send_mock, stripe_api):
    """Fail-closed: without the receipt in the chain nothing is done and the
    consumer gets an error — never a success that wasn't recorded."""
    monkeypatch.setitem(settings.__dict__, "audit_fail_closed", True)
    monkeypatch.setattr(
        billing_module,
        "record_event",
        AsyncMock(side_effect=audit_module.AuditWriteError("chain unavailable")),
    )
    asyncio.run(_insert_user())
    _one_live_pro_subscription(stripe_api)
    with TestClient(app, raise_server_exceptions=False) as raw_client:
        res = _post(raw_client)
    assert res.status_code == 500
    assert "chain" not in res.text
    stripe_api.list.assert_not_called()
    send_mock.assert_not_awaited()


# ── Rate limit ───────────────────────────────────────────────────────────────


def test_rate_limit_trips_on_the_11th_request(client, rate_limiter_enabled, send_mock):
    for i in range(10):
        res = _post(client)
        assert res.status_code == 200, f"request {i + 1}/10: {res.text}"
    sent_before = send_mock.await_count
    res = _post(client)
    assert res.status_code == 429
    assert send_mock.await_count == sent_before, "the 429 request must not send mail"
