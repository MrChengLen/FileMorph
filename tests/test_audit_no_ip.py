# SPDX-License-Identifier: AGPL-3.0-or-later
"""The audit log stores no IP addresses (decided 2026-09-28).

Until this change the audit events written for a request carried the
caller's address in ``audit_events.actor_ip`` — anonymous conversions
included — and the append-only table keeps its rows. Now nothing on the
audit path receives the client address, and the ORM no longer maps the
column. The column itself stays in every Alembic-managed database
(migration 005 creates it), NULL for new rows, until a migration drops
it.

Guards
------
1. ``record_event`` has no parameter that could carry an address, so a
   caller that still passes ``actor_ip`` fails loudly (``TypeError``)
   instead of storing it; ``AuditEvent`` has no such column.
2. Source scan over ``app/``: every call to the audit recorder uses only
   the allowed keywords, passes its payload as an inline dict, and
   nothing in its arguments reads the client address — also at call
   sites no route test reaches. The scan only sees what is written
   inside the call; an address laundered through an innocently named
   variable is left to the behaviour tests. The scan checks itself: it
   must find the known call sites and must flag planted offenders, so a
   rename can't turn it into a silent pass. ``actor_ip`` appears nowhere
   in ``app/`` code (catches raw SQL and a re-added mapping too).
3. Behaviour: requests from a fixed documentation address through the
   real routes and the real recorder leave that address in no column of
   any audit row, not even shortened or hashed, and the legacy
   ``actor_ip`` column stays NULL — success and failure paths, anonymous
   and signed in.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import io
import re
import tokenize
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import audit as audit_module
from app.core import email as email_mod
from app.core.audit import record_event
from app.db.base import Base, get_db
from app.db.models import AuditEvent, User
from app.main import app

# RFC 5737 documentation address (TEST-NET-3) — never a real client.
DOC_IP = "203.0.113.7"

_APP_DIR = Path(__file__).resolve().parent.parent / "app"
_ALLOWED_KEYWORDS = {"event_type", "actor_user_id", "payload", "db"}
# Tokens that point at a client address. Identifiers and strings are split
# at camelCase humps and on anything that isn't a letter or digit, so
# "client_ip", "_client_ip", "clientIp", "remoteAddr", "x-real-ip" and
# "X-Forwarded-For" all match while "email_hash" or "entities_redacted"
# don't.
_ADDRESS_TOKENS = {"ip", "addr", "address", "host", "client", "forwarded"}
# Helpers whose return value embeds the client address.
_ADDRESS_HELPERS = {"actor_id"}  # app/core/processing.py: "ip:<addr>"
# Every module that writes audit events today. The scan must find a call
# in each — otherwise it is looking at the wrong names.
_KNOWN_CALLERS = {
    "app/api/routes/ai.py",
    "app/api/routes/auth.py",
    "app/api/routes/billing.py",
    "app/api/routes/compress.py",
    "app/api/routes/contact.py",
    "app/api/routes/convert.py",
}


def _tokens(identifier: str) -> set[str]:
    identifier = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", identifier)
    return {t for t in re.split(r"[^a-z0-9]+", identifier.lower()) if t}


# ── 1. The recorder and the model take no address ────────────────────────────


def test_record_event_has_no_ip_parameter():
    params = set(inspect.signature(record_event).parameters)
    assert params == _ALLOWED_KEYWORDS, params


def test_chain_insert_has_no_ip_parameter():
    params = set(inspect.signature(audit_module._do_record).parameters)
    assert not {p for p in params if _tokens(p) & _ADDRESS_TOKENS}, params


def test_passing_an_ip_fails_loudly():
    """A forgotten caller must crash in tests, not store the address."""
    with pytest.raises(TypeError):
        record_event("test.event", actor_ip=DOC_IP)  # type: ignore[call-arg]


def test_audit_model_maps_no_ip_column():
    """SQLAlchemy writes every mapped column into each INSERT, so a mapped
    ``actor_ip`` would break every audit write once the column is dropped."""
    columns = set(AuditEvent.__table__.c.keys())
    assert not {c for c in columns if _tokens(c) & _ADDRESS_TOKENS}, columns


def _code_lines_naming(path: Path, needle: str) -> list[int]:
    """Lines where ``needle`` appears in a name, string or docstring —
    comments are skipped, so a note explaining the removal may name it."""
    with path.open("rb") as f:
        return [
            tok.start[0]
            for tok in tokenize.tokenize(f.readline)
            if needle in tok.string
            and (
                tok.type in (tokenize.NAME, tokenize.STRING)
                or tokenize.tok_name[tok.type].endswith("STRING_MIDDLE")  # f/t-strings
            )
        ]


def test_actor_ip_appears_nowhere_in_app_code():
    """Catches a re-added mapping, a stray keyword and raw SQL alike."""
    hits = [
        f"{path.relative_to(_APP_DIR.parent).as_posix()}:{lineno}"
        for path in sorted(_APP_DIR.rglob("*.py"))
        for lineno in _code_lines_naming(path, "actor_ip")
    ]
    assert not hits, hits


# ── 2. Source scan: no call site hands an address to the recorder ───────────


def _recorder_names(tree: ast.Module) -> set[str]:
    """``record_event`` plus every local alias it is imported under."""
    names = {"record_event"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").rsplit(".", 1)[-1] == "audit":
            for alias in node.names:
                if alias.name == "record_event":
                    names.add(alias.asname or alias.name)
    return names


def _recorder_calls(tree: ast.Module) -> list[ast.Call]:
    names = _recorder_names(tree)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in names:
            calls.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == "record_event":
            calls.append(node)
    return calls


def _address_leaks(call: ast.Call) -> list[str]:
    """Why this call could hand a client address to the audit log."""
    problems = []
    for kw in call.keywords:
        if kw.arg is None:
            problems.append("**kwargs (keywords can't be checked)")
        elif kw.arg not in _ALLOWED_KEYWORDS:
            problems.append(f"keyword {kw.arg!r}")
        elif kw.arg == "payload" and not isinstance(kw.value, ast.Dict):
            problems.append("payload built outside the call (can't be checked)")
        elif kw.arg == "payload" and None in kw.value.keys:
            problems.append("payload unpacks another mapping (can't be checked)")
    for sub in ast.walk(call):
        if (
            sub is not call
            and isinstance(sub, ast.Call)
            and any(
                isinstance(arg, ast.Name) and arg.id == "request"
                for arg in [*sub.args, *(k.value for k in sub.keywords)]
            )
        ):
            problems.append(f"passes the request object to {ast.unparse(sub.func)}()")
        if isinstance(sub, ast.Name):
            ident = sub.id
        elif isinstance(sub, ast.Attribute):
            ident = sub.attr
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            ident = sub.value  # e.g. a payload key such as "client_ip"
        else:
            continue
        if _tokens(ident) & _ADDRESS_TOKENS or ident in _ADDRESS_HELPERS:
            problems.append(f"reads {ident!r}")
    return problems


def _scan_app() -> dict[str, list[ast.Call]]:
    found: dict[str, list[ast.Call]] = {}
    for path in sorted(_APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_bytes(), filename=str(path))
        calls = _recorder_calls(tree)
        if calls:
            found[path.relative_to(_APP_DIR.parent).as_posix()] = calls
    return found


def test_scan_finds_every_known_caller():
    assert _KNOWN_CALLERS <= set(_scan_app()), sorted(_scan_app())


def test_scan_flags_a_planted_ip():
    """Self-test: the checker must catch each way an address could sneak in."""
    planted = ast.parse(
        "from app.core.audit import record_event as audit_record\n"
        "audit_record('a.b', actor_ip=request.client.host)\n"
        "audit_record('a.b', payload={'client_ip': x})\n"
        "audit_record('a.b', payload={'k': _client_ip(request)})\n"
        "audit_record('a.b', payload={'k': request.headers.get('X-Forwarded-For')})\n"
        "audit_record('a.b', payload={'k': request.headers['x-real-ip']})\n"
        "audit_record('a.b', payload={'actor': actor_id(request, user, tier)})\n"
        "audit_record('a.b', payload=details)\n"
        "audit_record('a.b', payload={**details, 'tier': tier})\n"
        "audit_record('a.b', payload={'k': _audit_meta(request)})\n"
        "audit_record('a.b', payload={'clientIp': x})\n"
        "audit_record('a.b', payload={'k': userIPHash})\n"
        "audit_record('a.b', **extra)\n"
        "audit_record('a.b', actor_user_id=user.id, payload={'tier': tier})\n"
    )
    verdicts = [bool(_address_leaks(c)) for c in _recorder_calls(planted)]
    assert verdicts == [True] * 12 + [False]
    relative = ast.parse(
        "from ..core.audit import record_event as log_event\n"
        "from .audit import record_event as rec\n"
        "log_event('a.b', actor_ip=request.client.host)\n"
        "rec('a.b', actor_ip=request.client.host)\n"
    )
    assert [bool(_address_leaks(c)) for c in _recorder_calls(relative)] == [True, True]


def test_no_audit_call_passes_a_client_address():
    offenders = [
        f"{path}:{call.lineno}: {', '.join(problems)}"
        for path, calls in _scan_app().items()
        for call in calls
        if (problems := _address_leaks(call))
    ]
    assert not offenders, "audit calls that could store an IP:\n" + "\n".join(offenders)


# ── 3. Behaviour: real routes, real recorder, fixed client address ───────────

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
        # Every Alembic-managed database still has this column (migration 005)
        # until a later migration drops it; the model no longer maps it.
        await conn.execute(text("ALTER TABLE audit_events ADD COLUMN actor_ip VARCHAR(45)"))


async def _wipe() -> None:
    async with _TestSession() as s:
        await s.execute(delete(AuditEvent))
        await s.execute(delete(User))
        await s.commit()


async def _override_get_db():
    async with _TestSession() as session:
        yield session


def _legacy_ips() -> list[str]:
    async def _q():
        async with _TestSession() as s:
            res = await s.execute(
                text("SELECT actor_ip FROM audit_events WHERE actor_ip IS NOT NULL")
            )
            return list(res.scalars().all())

    return asyncio.run(_q())


def _audit_rows() -> list[tuple]:
    """Every stored audit row, all columns, as plain tuples."""

    async def _q():
        async with _TestSession() as s:
            res = await s.execute(text("SELECT * FROM audit_events ORDER BY id"))
            return [tuple(row) for row in res.all()]

    return asyncio.run(_q())


@pytest.fixture(scope="module")
def ip_client():
    """A TestClient whose requests arrive from ``DOC_IP``, with the audit
    recorder and ``get_db`` pointed at a private in-memory database."""
    asyncio.run(_setup_schema())
    app.dependency_overrides[get_db] = _override_get_db
    original_session = audit_module.AsyncSessionLocal
    audit_module.AsyncSessionLocal = _TestSession
    try:
        with TestClient(app, client=(DOC_IP, 4711)) as c:
            yield c
    finally:
        audit_module.AsyncSessionLocal = original_session
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _clean_audit_table(request):
    if "ip_client" in request.fixturenames:
        asyncio.run(_wipe())
    yield


@pytest.fixture
def mail(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", mock)
    return mock


def _assert_no_address_stored(expected_events: set[str]) -> None:
    rows = _audit_rows()
    stored_events = {cell for row in rows for cell in row if cell in expected_events}
    assert stored_events == expected_events, f"missing audit events: {rows}"
    forms = ("203.0.113.", hashlib.sha256(DOC_IP.encode()).hexdigest())
    leaking = [row for row in rows if any(f in str(cell) for cell in row for f in forms)]
    assert not leaking, f"client address stored in audit rows: {leaking}"
    assert _legacy_ips() == [], "new rows must leave the legacy actor_ip column empty"


def _image(fmt: str, size: int) -> io.BytesIO:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (size, size), color=(200, 100, 50)).save(buf, format=fmt)
    buf.seek(0)
    return buf


def _token_from(mail: AsyncMock) -> str:
    body = mail.await_args.kwargs["text"]
    assert "token=" in body, body
    return body[body.find("token=") + len("token=") :].split()[0].strip()


def test_anonymous_convert_and_compress_store_no_ip(ip_client, auth_headers):
    """The case that prompted the decision: a caller without an account
    (API key from the key file) still got its address in every row."""
    blocked = io.BytesIO(b"MZ" + b"\0" * 64)  # BLOCKED_MAGIC → 400 → *.failure
    for route, name, data, mime in [
        ("/api/v1/convert", "a.png", {"target_format": "jpg"}, "image/png"),
        ("/api/v1/compress", "a.jpg", {"quality": "50"}, "image/jpeg"),
    ]:
        ok = _image("PNG" if name.endswith("png") else "JPEG", 32)
        res = ip_client.post(
            route, files={"file": (name, ok, mime)}, data=data, headers=auth_headers
        )
        assert res.status_code == 200, res.text
        blocked.seek(0)
        res = ip_client.post(
            route, files={"file": (name, blocked, mime)}, data=data, headers=auth_headers
        )
        assert res.status_code == 400, res.text

    _assert_no_address_stored(
        {"convert.success", "convert.failure", "compress.success", "compress.failure"}
    )


def test_account_lifecycle_stores_no_ip(ip_client, mail):
    """Registration through deletion — every auth event of one account."""
    creds = {"email": "no-ip@example.com", "password": "abcdefghi"}

    res = ip_client.post("/api/v1/auth/register", json=creds)
    assert res.status_code == 201, res.text
    res = ip_client.post("/api/v1/auth/verify-email", json={"token": _token_from(mail)})
    assert res.status_code == 200, res.text
    assert ip_client.post("/api/v1/auth/register", json=creds).status_code == 409
    wrong = {**creds, "password": "wrong-password"}
    assert ip_client.post("/api/v1/auth/login", json=wrong).status_code == 401

    res = ip_client.post("/api/v1/auth/forgot-password", json={"email": creds["email"]})
    assert res.status_code == 200, res.text
    new_password = "brand-new-pw-456"
    res = ip_client.post(
        "/api/v1/auth/reset-password",
        json={"token": _token_from(mail), "new_password": new_password},
    )
    assert res.status_code == 200, res.text

    res = ip_client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": new_password}
    )
    assert res.status_code == 200, res.text
    res = ip_client.request(
        "DELETE",
        "/api/v1/auth/account",
        headers={"Authorization": f"Bearer {res.json()['access_token']}"},
        json={
            "password": new_password,
            "confirm_email": creds["email"],
            "confirm_word": "DELETE",
        },
    )
    assert res.status_code == 204, res.text

    _assert_no_address_stored(
        {
            "auth.register.success",
            "auth.email_verification.requested",
            "auth.email_verification.completed",
            "auth.register.duplicate",
            "auth.login.failure",
            "auth.password_reset.requested",
            "auth.password_reset.completed",
            "auth.login.success",
            "auth.account_deletion.requested",
            "auth.account_deletion.completed",
        }
    )


def test_contact_message_stores_no_ip(ip_client, mail):
    res = ip_client.post(
        "/api/v1/contact",
        json={
            "name": "Erika Mustermann",
            "email": "erika@example.com",
            "subject": "Hello",
            "message": "x" * 25,
            "website": "",
        },
    )
    assert res.status_code == 200, res.text

    _assert_no_address_stored({"contact.message.received"})


# ── 4. The privacy page says so — in both languages ──────────────────────────


@pytest.mark.parametrize(
    "path, phrases",
    [
        (
            "/en/privacy",
            ["2h. Audit log (Cloud Edition):", "no longer records IP addresses", "time limit"],
        ),
        (
            "/de/privacy",
            [
                "2h. Audit-Log (Cloud Edition):",
                "keine IP-Adressen mehr",
                "zeitliche Begrenzung",
            ],
        ),
    ],
)
def test_privacy_page_discloses_the_audit_log(client, path, phrases):
    body = client.get(path).text
    missing = [p for p in phrases if p not in body]
    assert not missing, missing
    if path.startswith("/de/"):
        # A missing or fuzzy translation silently falls back to English.
        for english in ("no longer records IP addresses", "So that we can prove afterwards"):
            assert english not in body, english


def test_docs_list_no_audit_ip():
    """The DPA, records-of-processing, questionnaire and self-hosting texts
    used to list an ``actor_ip`` / "actor IP" — they must not again."""
    root = _APP_DIR.parent
    files = [*sorted((root / "docs").glob("*.md")), root / "README.md", root / ".env.example"]
    hits = [
        f"{f.relative_to(root).as_posix()}:{lineno}"
        for f in files
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bactor[ _-]?ip\b", line, re.IGNORECASE)
    ]
    assert not hits, hits
