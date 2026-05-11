# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import email as email_mod
from app.core.audit import record_event as audit_record
from app.core.auth import hash_password, verify_password
from app.core.i18n import SUPPORTED_LOCALES, get_locale
from app.core.tokens import (
    create_access_token,
    create_email_verify_token,
    create_password_reset_token,
    create_refresh_token,
    decode_email_verify_token,
    decode_password_reset_token,
    decode_token,
    password_hash_version,
)
from app.core.config import settings
from app.core.metrics import increment as metric_increment
from app.core.rate_limit import limiter
from app.db.base import get_db
from app.db.models import ApiKey, RoleEnum, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────


_PASSWORD_MAX = 128
"""Hard cap on inbound passwords. bcrypt itself silently truncates at 72
bytes, but accepting megabyte-sized inputs would let a caller burn
server CPU on the bcrypt work-factor with each login attempt — a cheap
DoS vector. 128 is comfortably past every real-world password manager
and well below where bcrypt's truncation matters."""


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=_PASSWORD_MAX)

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=_PASSWORD_MAX)


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
    # PR-J: mirrors the Stripe subscription status so the dashboard can
    # surface a "payment issue — update your card" banner when this is
    # ``past_due`` / ``incomplete``. ``None`` = never subscribed.
    subscription_status: str | None = None
    # PR-i18n-3: the language transactional email is sent in (``de`` /
    # ``en``). ``None`` = no explicit preference → operator default
    # (``LANG_DEFAULT``). Set via PUT /auth/account/language.
    preferred_lang: str | None = None


class PreferredLanguageRequest(BaseModel):
    preferred_lang: str

    @field_validator("preferred_lang")
    @classmethod
    def _supported_locale(cls, v: str) -> str:
        if v not in SUPPORTED_LOCALES:
            raise ValueError(f"unsupported locale; choose one of {sorted(SUPPORTED_LOCALES)}")
        return v


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., max_length=_PASSWORD_MAX)

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


class VerifyEmailRequest(BaseModel):
    token: str


class DeleteAccountRequest(BaseModel):
    """Three-field re-confirmation: each field defends a different mistake.

    * ``password`` — defends against a stolen JWT being used by someone
      who doesn't know the password.
    * ``confirm_email`` — defends against the user being signed into the
      wrong account.
    * ``confirm_word`` — defends against an accidental form submission;
      must be the literal string ``DELETE``.

    See ``docs/gdpr-account-deletion-design.md`` § 3 for the rationale.
    """

    password: str = Field(..., max_length=_PASSWORD_MAX)
    confirm_email: EmailStr
    confirm_word: str

    @field_validator("confirm_word")
    @classmethod
    def must_be_literal_DELETE(cls, v: str) -> str:
        if v != "DELETE":
            raise ValueError('confirm_word must be exactly "DELETE".')
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


def _support_contact() -> str:
    """Best-effort support address for user-facing copy.

    Self-hosters configure their own SMTP identity, so any hardcoded
    ``@filemorph.io`` address would ship our cloud team's inbox into
    third-party deployments — a scope-review.py "deployment-agnostic"
    violation. Prefer the operator's reply-to, fall back to the FROM
    address, and only fall back to a neutral phrase when neither is
    set (e.g. tests with no SMTP configured)."""
    return settings.smtp_reply_to or settings.smtp_from_email or "your administrator"


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
    # PR-i18n-3: seed the user's transactional-email language from the
    # locale they signed up in (URL prefix / Accept-Language / operator
    # default — see app/core/i18n.py). They can change it from the
    # dashboard later; outbound mail with no request context (dunning)
    # falls back to this column.
    locale = await get_locale(request)
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        preferred_lang=locale,
    )
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
    # NEU-B.3 (slice b): kick off the verification email. Fire-and-forget —
    # SMTP failures are logged but do not block registration. The user
    # gets logged in immediately; any feature that wants verified status
    # later checks ``user.email_verified_at IS NOT NULL``.
    await _send_verify_email_safe(user, locale)
    await audit_record(
        "auth.email_verification.requested",
        actor_user_id=user.id,
        actor_ip=_client_ip(request),
        payload={"trigger": "register"},
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


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        tier=user.tier.value,
        role=user.role.value,
        created_at=user.created_at,
        subscription_status=user.subscription_status,
        preferred_lang=user.preferred_lang,
    )


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return _user_response(user)


@router.put("/account/language", response_model=UserResponse)
async def set_preferred_language(
    body: PreferredLanguageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db),
):
    """Set the language FileMorph sends this user's transactional email in.

    Persisted on ``users.preferred_lang``. Used wherever email is rendered
    outside an HTTP request (the dunning mail fired from a Stripe webhook)
    and as the first choice for request-context mail too (reset / resend /
    deletion confirmation). It does **not** change the web-UI locale, which
    stays URL-prefix-driven — see ``app/core/i18n.py``.

    Auth: JWT bearer (``get_current_user``), like ``GET /auth/me``. Body:
    ``{"preferred_lang": "de" | "en"}`` — an unsupported value is a 422
    from the Pydantic validator.
    """
    db = _db_required(db)
    user.preferred_lang = body.preferred_lang
    await db.commit()
    await db.refresh(user)
    return _user_response(user)


_ENUMERATION_SAFE_RESPONSE = {
    "message": "If this email exists, you'll receive a reset link shortly."
}


def _build_reset_url(token: str) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/reset-password?token={token}"


def _render_reset_emails(user_email: str, reset_url: str, locale: str) -> tuple[str, str, str]:
    return email_mod.render_email(
        "password_reset",
        locale=locale,
        user_email=user_email,
        reset_url=reset_url,
        app_base_url=settings.app_base_url.rstrip("/"),
    )


# ── Email-verification helpers (NEU-B.3 slice b) ──────────────────────────────


def _build_verify_url(token: str) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/verify-email?token={token}"


def _render_verify_emails(user_email: str, verify_url: str, locale: str) -> tuple[str, str, str]:
    return email_mod.render_email(
        "verify_email",
        locale=locale,
        user_email=user_email,
        verify_url=verify_url,
        app_base_url=settings.app_base_url.rstrip("/"),
    )


async def _send_verify_email_safe(user: User, locale: str) -> None:
    """Fire-and-forget verification email — never raises into the caller.

    Used from /register (right after the user row is committed) and from
    /resend-verification. SMTP failures are logged but do not roll back
    the underlying state change: a user who never gets the email can
    request another one via the resend route. ``locale`` picks the
    language — the registration locale at /register, or the user's saved
    ``preferred_lang`` (falling back to the request locale) on resend."""
    token = create_email_verify_token(str(user.id), user.email)
    verify_url = _build_verify_url(token)
    subject, html, text = _render_verify_emails(
        user_email=user.email, verify_url=verify_url, locale=locale
    )
    try:
        await email_mod.send_email(to=user.email, subject=subject, html=html, text=text)
        logger.info("verify_email: dispatched user=%s", user.id)
    except email_mod.EmailSendError:
        logger.exception("verify_email: delivery failed user=%s", user.id)


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
    # An explicit account-level email-language preference wins over the
    # locale of whatever device requested the reset; otherwise match the
    # request context.
    locale = user.preferred_lang or await get_locale(request)
    subject, html, text = _render_reset_emails(
        user_email=user.email, reset_url=reset_url, locale=locale
    )

    try:
        await email_mod.send_email(to=user.email, subject=subject, html=html, text=text)
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


# ── Email verification endpoints (NEU-B.3 slice b) ────────────────────────────


@router.post("/verify-email", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    body: VerifyEmailRequest,
    db: AsyncSession | None = Depends(get_db),
):
    """Consume a verification token and stamp ``email_verified_at``.

    Idempotent: re-verifying an already-verified email returns 200 with
    a no-op confirmation. The ``eat`` claim binds the token to the
    user's email at issuance time, so a token issued before an email
    rotation cannot auto-verify the new address."""
    db = _db_required(db)
    user_id, email_at_issuance = decode_email_verify_token(body.token)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link is invalid or has expired.",
        )
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link is invalid or has expired.",
        )
    # Email rotation since the token was issued silently invalidates the
    # link — same UX as password-reset's phv-mismatch path.
    if user.email != email_at_issuance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link is no longer valid.",
        )

    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        await db.commit()
        # NEU-B.3: ISO 27001 A.9.2.1 — credential / identity-binding
        # changes are audit-relevant. Same "commit then audit" ordering
        # as password-reset.completed; under audit_fail_closed the
        # state change has already landed if the audit insert fails.
        await audit_record(
            "auth.email_verification.completed",
            actor_user_id=user.id,
            actor_ip=_client_ip(request),
        )
        logger.info("verify_email: user=%s verified", user.id)

    return {"message": "Email verified."}


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def resend_verification(request: Request, user: User = Depends(get_current_user)):
    """Send a fresh verification email to the authenticated user.

    Auth-required so the endpoint can't be used as a free email-spam
    vector. Returns 200 with a no-op message when the email is already
    verified (rather than 4xx) — the user-visible UX is "we tried to
    help you" regardless of state, and we never confirm verification
    state of an arbitrary email to an unauthenticated caller."""
    if user.email_verified_at is not None:
        return {"message": "Email already verified."}
    await _send_verify_email_safe(user, user.preferred_lang or await get_locale(request))
    await audit_record(
        "auth.email_verification.requested",
        actor_user_id=user.id,
        actor_ip=_client_ip(request),
        payload={"trigger": "resend"},
    )
    return {"message": "Verification email sent."}


# ── Account deletion (NEU-B.3 slice c.1, free path only) ──────────────────────


_DELETE_GENERIC_400 = "Confirmation did not match."


def _render_account_deleted_emails(
    user_email: str, deleted_at_iso: str, locale: str
) -> tuple[str, str, str]:
    return email_mod.render_email(
        "account_deleted",
        locale=locale,
        user_email=user_email,
        deleted_at=deleted_at_iso,
        app_base_url=settings.app_base_url.rstrip("/"),
        support_email=_support_contact(),
    )


async def _send_account_deleted_email_safe(
    user_email: str, deleted_at_iso: str, locale: str
) -> None:
    """Confirmation email after a successful deletion. Never raises into
    the caller — the deletion is already final, the email is informational.
    A delivery failure is logged for the operator audit trail. ``locale``
    is captured from the row before it is deleted (the user's
    ``preferred_lang``, falling back to the request locale)."""
    subject, html, text = _render_account_deleted_emails(user_email, deleted_at_iso, locale)
    try:
        await email_mod.send_email(to=user_email, subject=subject, html=html, text=text)
    except email_mod.EmailSendError:
        logger.exception("account_deletion: confirmation email failed for %s", user_email)


async def _is_last_active_admin(db: AsyncSession, user: User) -> bool:
    """Defends against a deployment locking itself out of the admin cockpit.

    Self-hosters typically run with a single admin account; the cloud op
    has more, but the guard belongs in the endpoint either way. If the
    caller is not an admin the answer is trivially False."""
    if user.role != RoleEnum.admin:
        return False
    result = await db.execute(
        select(func.count(User.id)).where(
            User.role == RoleEnum.admin,
            User.is_active.is_(True),
        )
    )
    active_admin_count = int(result.scalar_one())
    return active_admin_count <= 1


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("1/minute")
async def delete_account(
    request: Request,
    body: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession | None = Depends(get_db),
):
    """Self-service account deletion (DSGVO Art. 17).

    This is the **free-path** slice of the design in
    ``docs/gdpr-account-deletion-design.md``. It hard-deletes accounts
    that have never been linked to Stripe. Accounts with an active or
    historical Stripe customer record are refused with 409 and pointed
    at ``privacy@`` until the paid-path tax-retention flow lands
    (HGB §257, AO §147 — slice c.2).

    Auth: JWT bearer only. ``X-API-Key`` is intentionally rejected
    because the API key is one of the things being deleted; using the
    very key whose deletion is requested has chicken-and-egg semantics.
    The route's ``Depends(get_current_user)`` already enforces JWT-only
    by reading the ``Authorization`` header and ignoring ``X-API-Key``.

    Re-confirmation: three fields must match (``password``,
    ``confirm_email``, ``confirm_word=='DELETE'``). All three failures
    return the same generic 400 so a stolen-JWT attacker cannot probe
    which field is wrong.
    """
    db = _db_required(db)

    # Re-confirmation gate — uniform 400 on any mismatch.
    if body.confirm_email.lower() != user.email.lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_DELETE_GENERIC_400)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_DELETE_GENERIC_400)
    # ``confirm_word`` was validated by the Pydantic field validator.

    # Tax-retention guard: any account that has touched Stripe needs the
    # paid-path flow that's not implemented yet. Refusing here is the
    # correct German-law-conformant behaviour until slice c.2 ships.
    if user.stripe_customer_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Paid accounts must be deleted via {_support_contact()} while we "
                "complete the tax-retention flow (HGB §257)."
            ),
        )

    # Last-admin guard.
    if await _is_last_active_admin(db, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You are the only active admin. Promote another user to admin "
                "before deleting your account."
            ),
        )

    user_id = user.id
    user_email = user.email
    email_domain = user_email.split("@", 1)[1] if "@" in user_email else "unknown"
    had_subscription = bool(user.stripe_customer_id)
    deleted_at_iso = datetime.now(timezone.utc).isoformat()
    # Capture the email language before the row is gone — the user's saved
    # preference, falling back to the locale of the deletion request.
    email_locale = user.preferred_lang or await get_locale(request)

    # NEU-B.3: record the *intent* before destroying the row. Once the
    # commit lands, ``actor_user_id`` becomes a dangling FK that the
    # audit-events ``ON DELETE SET NULL`` cascade nulls — but the
    # event_type + payload + occurred_at survive for the auditor.
    await audit_record(
        "auth.account_deletion.requested",
        actor_user_id=user_id,
        actor_ip=_client_ip(request),
        payload={
            "email_domain": email_domain,
            "had_subscription": had_subscription,
            "deletion_mode": "free",
        },
    )

    # PostgreSQL handles the related-row cascade via the ON DELETE
    # clauses on api_keys (CASCADE), file_jobs (SET NULL), and
    # usage (SET NULL) — see app/db/models.py. SQLAlchemy's
    # ``cascade='all, delete-orphan'`` on User.api_keys would lazy-load
    # the collection on flush; on the async session that triggers a
    # MissingGreenlet error if any keys exist. Re-fetch with
    # ``selectinload`` so the relationship is preloaded before
    # ``db.delete`` walks the cascade.
    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.api_keys))
    )
    user = result.scalar_one()
    await db.delete(user)
    await db.commit()

    logger.info(
        "account_deletion",
        extra={
            "user_id": str(user_id),
            "email_domain": email_domain,
            "had_subscription": had_subscription,
            "deletion_mode": "free",
        },
    )
    await audit_record(
        "auth.account_deletion.completed",
        actor_ip=_client_ip(request),
        payload={
            "email_domain": email_domain,
            "deletion_mode": "free",
        },
    )
    await _send_account_deleted_email_safe(user_email, deleted_at_iso, email_locale)
    # 204 No Content — body intentionally empty.
    return None
