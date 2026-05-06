# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.compat import base_dir
from app.core import email as email_mod
from app.core.audit import record_event as audit_record
from app.core.auth import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_password_reset_token,
    decode_token,
    hash_password,
    password_hash_version,
    verify_password,
)
from app.core.config import settings
from app.core.metrics import increment as metric_increment
from app.core.rate_limit import limiter
from app.db.base import get_db
from app.db.models import ApiKey, RoleEnum, User

logger = logging.getLogger(__name__)

_EMAIL_TEMPLATE_DIR = base_dir() / "app" / "templates" / "emails"
_email_env = Environment(
    loader=FileSystemLoader(str(_EMAIL_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    enable_async=False,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    tier: str
    role: str
    created_at: datetime


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


# ── Dependency ────────────────────────────────────────────────────────────────


async def get_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession | None = Depends(get_db),
) -> User:
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not configured."
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    token = authorization.removeprefix("Bearer ")
    user_id = decode_token(token, expected_type="access")
    # asyncpg happily binds a str to a UUID column, but SQLAlchemy's generic
    # UUID type (used by the SQLite test engine) calls ``.hex`` on the value
    # and blows up on bare strings. Cast explicitly so the dependency works
    # on any backend and rejects malformed subjects cleanly.
    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    result = await db.execute(select(User).where(User.id == user_uuid, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user


async def get_optional_user(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    db: AsyncSession | None = Depends(get_db),
) -> User | None:
    """Resolve the caller to a ``User`` if possible, else ``None``.

    Two auth paths land on upload endpoints: the Web UI sends the JWT from
    /login (``Authorization: Bearer``), while API/CLI callers send an
    ``X-API-Key`` minted from the /dashboard. Both must resolve to the same
    ``User`` so tier-based quotas (batch size, file size, output cap) match
    the account. Bearer is preferred — it carries identity directly; the
    X-API-Key fallback looks up the DB-registered key by SHA-256 hash.
    """
    if db is None:
        return None
    if authorization and authorization.startswith("Bearer "):
        try:
            return await get_current_user(authorization=authorization, db=db)
        except HTTPException:
            pass
    if x_api_key:
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        result = await db.execute(
            select(ApiKey)
            .where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
            .options(selectinload(ApiKey.user))
        )
        api_key = result.scalar_one_or_none()
        if api_key and api_key.user and api_key.user.is_active:
            # Best-effort last-used timestamp; a transient commit failure
            # must not break the request the key was attached to.
            api_key.last_used_at = datetime.now(timezone.utc)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            return api_key.user
    return None


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Gate an endpoint to admin role. Re-reads ``role`` from the loaded User
    instance so a promotion/demotion in the DB takes effect on the next request
    (the claim in the JWT is not trusted on its own)."""
    if current_user.role != RoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required."
        )
    return current_user


def _db_required(db: AsyncSession | None) -> AsyncSession:
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not configured."
        )
    return db


def _email_hash(email: str) -> str:
    """Lowercased SHA-256 of an email address.

    Used in audit-event payloads for ``auth.login.failure`` and
    ``auth.password_reset.requested`` so the chain records "this
    email-shape was attempted N times" without recording the email
    itself. Two reasons:

    - Email addresses are PII (DSGVO Art. 4 Nr. 1). Storing them in
      an append-only chain that may live for years exceeds the
      data-minimisation principle (DSGVO Art. 5 Abs. 1 lit. c).
    - An attacker who later exfiltrates the audit table learns
      every email anyone ever tried to log in with. Hashing turns
      that into "every email-hash anyone ever tried" — still useful
      for failure-rate analysis, useless for credential stuffing.

    Lowercased before hashing so ``Foo@Example.com`` and
    ``foo@example.com`` collide on the same hash, matching the
    existing case-insensitive lookup in ``forgot_password``.
    """
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or ``None`` if the harness left
    ``request.client`` unset (TestClient sometimes does)."""
    return request.client.host if request.client else None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request, body: RegisterRequest, db: AsyncSession | None = Depends(get_db)
):
    db = _db_required(db)
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        # NEU-B.3: surface the duplicate-email attempt to the audit chain
        # using the hash, not the address — enumeration-pattern visibility
        # without the chain becoming a directory of every email anyone
        # ever attempted.
        await audit_record(
            "auth.register.duplicate",
            actor_ip=_client_ip(request),
            payload={"email_hash": _email_hash(body.email)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered."
        )
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    # S10-lite: count successful registrations for the cockpit Analytics view.
    # increment owns its session — kept off the request transaction so a
    # metrics failure here can't corrupt the freshly committed user row.
    await metric_increment("registrations")
    # NEU-B.3: ISO 27001 A.9.2.1 — record account creation with the new
    # user's id as actor. ``audit_record`` opens its own session so a
    # failure here can never corrupt the freshly committed user row.
    await audit_record(
        "auth.register.success",
        actor_user_id=user.id,
        actor_ip=_client_ip(request),
    )
    return TokenResponse(
        access_token=create_access_token(str(user.id), role=user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession | None = Depends(get_db)):
    db = _db_required(db)
    result = await db.execute(
        select(User).where(User.email == body.email, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        # NEU-B.3: ISO 27001 A.9.4.2 — record failed authentication. No
        # actor_user_id (we don't reveal whether the email exists; the
        # email_hash is enough to correlate brute-force attempts across
        # the same target without storing the address itself).
        await audit_record(
            "auth.login.failure",
            actor_ip=_client_ip(request),
            payload={"email_hash": _email_hash(body.email)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        )
    # NEU-B.3: successful authentication, with user identity. The
    # session-token issuance below is contingent on this audit row
    # under audit_fail_closed=True (Compliance edition).
    await audit_record(
        "auth.login.success",
        actor_user_id=user.id,
        actor_ip=_client_ip(request),
    )
    return TokenResponse(
        access_token=create_access_token(str(user.id), role=user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession | None = Depends(get_db)):
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    role = RoleEnum.user.value
    if db is not None:
        result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        user = result.scalar_one_or_none()
        if user:
            role = user.role.value
    return TokenResponse(
        access_token=create_access_token(user_id, role=role),
        refresh_token=create_refresh_token(user_id),
    )


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(user.id),
        email=user.email,
        tier=user.tier.value,
        role=user.role.value,
        created_at=user.created_at,
    )


_ENUMERATION_SAFE_RESPONSE = {
    "message": "If this email exists, you'll receive a reset link shortly."
}


def _build_reset_url(token: str) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/reset-password?token={token}"


def _render_reset_emails(user_email: str, reset_url: str) -> tuple[str, str]:
    ctx = {
        "user_email": user_email,
        "reset_url": reset_url,
        "app_base_url": settings.app_base_url.rstrip("/"),
    }
    html = _email_env.get_template("password_reset.html").render(**ctx)
    text = _email_env.get_template("password_reset.txt").render(**ctx)
    return html, text


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request, body: ForgotPasswordRequest, db: AsyncSession | None = Depends(get_db)
):
    # Always return the same payload, whether or not the email exists —
    # this keeps the endpoint enumeration-safe. Any branching / error is
    # logged server-side only.
    if db is None:
        logger.warning("forgot_password: DB not configured, returning generic 200")
        return _ENUMERATION_SAFE_RESPONSE

    result = await db.execute(select(User).where(User.email.ilike(body.email)))
    user = result.scalar_one_or_none()
    # NEU-B.3: every reset-request lands in the audit chain — both the
    # match-and-send path and the no-match early-return path — keyed by
    # email_hash so an auditor can see "thousands of resets attempted
    # against this email-shape" without us logging the email itself.
    await audit_record(
        "auth.password_reset.requested",
        actor_user_id=user.id if user is not None else None,
        actor_ip=_client_ip(request),
        payload={"email_hash": _email_hash(body.email)},
    )
    if user is None or not user.is_active:
        email_domain = body.email.split("@", 1)[-1] if "@" in body.email else "invalid"
        logger.info("forgot_password: no active user (domain=%s, no email sent)", email_domain)
        return _ENUMERATION_SAFE_RESPONSE

    phv = password_hash_version(user.password_hash)
    token = create_password_reset_token(str(user.id), phv)
    reset_url = _build_reset_url(token)
    html, text = _render_reset_emails(user_email=user.email, reset_url=reset_url)

    try:
        await email_mod.send_email(
            to=user.email,
            subject="Reset your FileMorph password",
            html=html,
            text=text,
        )
        logger.info("forgot_password: reset email dispatched user=%s", user.id)
    except email_mod.EmailSendError:
        # Already logged inside send_email. Still return 200 so an attacker
        # can't distinguish "email exists but SMTP down" from "email unknown".
        logger.exception("forgot_password: email delivery failed user=%s", user.id)

    return _ENUMERATION_SAFE_RESPONSE


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def reset_password(
    request: Request, body: ResetPasswordRequest, db: AsyncSession | None = Depends(get_db)
):
    db = _db_required(db)
    user_id, token_phv = decode_password_reset_token(body.token)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or has expired.",
        )
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or has expired.",
        )
    # phv mismatch = password has been changed since the token was issued
    # (either by a prior successful reset or by an admin). Reject.
    if password_hash_version(user.password_hash) != token_phv:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is no longer valid.",
        )

    user.password_hash = hash_password(body.new_password)
    await db.commit()
    logger.info("reset_password: password updated user=%s", user.id)
    # NEU-B.3: ISO 27001 A.9.2.4 — credential changes are audit-relevant.
    # Order is "commit then audit" because the audit log uses its own
    # session and there is no two-phase commit between the user-table
    # write and the audit-events insert. Under ``audit_fail_closed``,
    # a failure here surfaces as a 500 *after* the password change
    # has already landed; the chain still records the attempt on the
    # next successful operation by this user. A future iteration that
    # binds the audit insert into the same DB transaction (single-DB
    # deployments) closes that gap; cross-DB Compliance setups need a
    # separate design.
    await audit_record(
        "auth.password_reset.completed",
        actor_user_id=user.id,
        actor_ip=_client_ip(request),
    )
    return {"message": "Password updated."}
