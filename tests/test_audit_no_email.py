# SPDX-License-Identifier: AGPL-3.0-or-later
"""No audit entry keeps anything derived from an email address.

The audit payload is inside ``record_hash``, so nothing in it can ever be
erased. An email address, its SHA-256 (anyone who knows the address can
recompute that) or its domain (a personal domain names its owner) would
stay there for good: after the account is deleted, and also for people who
never had an account. An event about an existing account names it by
``actor_user_id`` instead, which is outside the hash and cleared when the
account is deleted.

Two checks:

- A static scan of every audit call in ``app/``: nothing handed over as
  payload or actor may be named after an email address.
- A behaviour test that drives every auth and contact route taking an
  email address and checks every column of every audit row those requests
  wrote. The online cancellation needs Stripe mocks; its own tests
  (``tests/test_billing_cancellation.py``) check its rows the same way.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import audit as audit_module
from app.core import email as email_mod
from app.db.base import Base, get_db
from app.main import app

# ── Static scan ──────────────────────────────────────────────────────

_APP_DIR = Path(__file__).resolve().parent.parent / "app"


def _recorder_calls(tree: ast.Module) -> list[ast.Call]:
    """Calls of ``record_event``, under any name it is imported as."""
    names = {"record_event"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.core.audit":
            names |= {a.asname or a.name for a in node.names if a.name == "record_event"}
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in names)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "record_event")
        )
    ]


def _email_leaks(call: ast.Call) -> list[str]:
    """Names and strings in the payload or the actor that say "mail". The
    event type is not checked: ``auth.email_verification.sent`` is fine."""
    leaks = []
    for keyword in call.keywords:
        if keyword.arg is None:
            leaks.append("** arguments cannot be checked")
            continue
        if keyword.arg not in ("payload", "actor_user_id"):
            continue
        if keyword.arg == "payload" and not isinstance(keyword.value, ast.Dict):
            leaks.append("payload is not an inline dict, so it cannot be checked")
            continue
        for node in ast.walk(keyword.value):
            if isinstance(node, ast.Name):
                word = node.id
            elif isinstance(node, ast.Attribute):
                word = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                word = node.value
            else:
                continue
            if "mail" in word.lower():
                leaks.append(word)
    return leaks


def _scan_app() -> dict[str, list[ast.Call]]:
    found = {}
    for path in sorted(_APP_DIR.rglob("*.py")):
        calls = _recorder_calls(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if calls:
            found[path.relative_to(_APP_DIR).as_posix()] = calls
    return found


def test_scan_sees_the_routes_that_take_an_email_address():
    assert {"api/routes/auth.py", "api/routes/billing.py", "api/routes/contact.py"} <= set(
        _scan_app()
    )


def test_scan_flags_a_planted_email_value():
    planted = ast.parse('record_event("x.y", payload={"domain": body.email.split("@")[1]})')
    assert _email_leaks(_recorder_calls(planted)[0]) == ["email"]


def test_no_audit_call_hands_over_email_derived_data():
    leaks = {
        f"{path}:{call.lineno}": _email_leaks(call)
        for path, calls in _scan_app().items()
        for call in calls
    }
    assert not {where: found for where, found in leaks.items() if found}


# ── Behaviour ────────────────────────────────────────────────────────

_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)

_PASSWORD = "initial-password"
# Mixed case and unusual parts, so no other value in a row can match them.
_HOLDER = "Guard.Holder@Holder-7f3a.example.com"  # registers, then deletes the account
_STRANGER = "Guard.Stranger@Stranger-7f3a.example.net"  # never has an account
_SENDER = "Guard.Sender@Sender-7f3a.example.org"  # writes through the contact form


def _derived(email: str) -> set[str]:
    """The address and everything that points back to it, in each form it
    takes: as typed, as ``EmailStr`` hands it to the routes (domain lower-
    cased, which is also what the users table stores) and all lower case
    (what the code used to hash). For each: the address, its local part,
    its domain and its SHA-256."""
    local, domain = email.split("@", 1)
    values = set()
    for form in (email, f"{local}@{domain.lower()}", email.lower()):
        values |= {form, *form.split("@", 1), hashlib.sha256(form.encode("utf-8")).hexdigest()}
    return values


async def _override_get_db():
    async with _Session() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    async def _create_schema():
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_schema())
    app.dependency_overrides[get_db] = _override_get_db
    original = audit_module.AsyncSessionLocal
    audit_module.AsyncSessionLocal = _Session
    yield
    audit_module.AsyncSessionLocal = original
    app.dependency_overrides.pop(get_db, None)


def _audit_rows() -> list[dict]:
    """Every column of every row, straight from the table — not only the
    ones the model maps."""

    async def _query():
        async with _Session() as s:
            result = await s.execute(text("SELECT * FROM audit_events ORDER BY id"))
            return [dict(row) for row in result.mappings().all()]

    return asyncio.run(_query())


def test_no_audit_payload_keeps_email_derived_data(client, monkeypatch):
    monkeypatch.setattr(email_mod, "send_email", AsyncMock())

    account = {"email": _HOLDER, "password": _PASSWORD}
    res = client.post("/api/v1/auth/register", json=account)
    assert res.status_code == 201, res.text
    token = res.json()["access_token"]
    assert client.post("/api/v1/auth/register", json=account).status_code == 409
    for email in (_HOLDER, _STRANGER):
        wrong = {"email": email, "password": "wrong-password"}
        assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
        reset = client.post("/api/v1/auth/forgot-password", json={"email": email})
        assert reset.status_code == 200
    message = {"name": "S", "email": _SENDER, "subject": "Hi", "message": "x" * 25, "website": ""}
    assert client.post("/api/v1/contact", json=message).status_code == 200
    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json={"password": _PASSWORD, "confirm_email": _HOLDER, "confirm_word": "DELETE"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204, res.text

    rows = _audit_rows()
    assert {row["event_type"] for row in rows} >= {
        "auth.register.success",
        "auth.register.duplicate",
        "auth.login.failure",
        "auth.password_reset.requested",
        "contact.message.received",
        "auth.account_deletion.requested",
        "auth.account_deletion.completed",
    }
    forbidden = _derived(_HOLDER) | _derived(_STRANGER) | _derived(_SENDER)
    for row in rows:
        for column, stored in row.items():
            for value in forbidden:
                assert value not in str(stored), f"{row['event_type']}.{column} keeps {value!r}"


@pytest.mark.parametrize(
    ("path", "phrases", "foreign"),
    [
        (
            "/en/privacy",
            ["not a hash of it, not its domain", "up to and including 12 October 2026"],
            [],
        ),
        (
            "/de/privacy",
            [
                "weder die Adresse noch einen Hash davon noch ihre Domain",
                "bis einschließlich 12. Oktober 2026",
            ],
            # A missing or fuzzy translation falls back to English silently.
            ["New entries record your email address", "Entries written up to and including"],
        ),
    ],
)
def test_privacy_page_says_audit_entries_keep_no_email_data(client, path, phrases, foreign):
    body = client.get(path).text
    assert [p for p in phrases if p not in body] == []
    assert [p for p in foreign if p in body] == []
