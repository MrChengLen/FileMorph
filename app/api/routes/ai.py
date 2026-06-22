# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI file operations — HTTP controller (thin, AGPL).

This is the gated entry point for the Enterprise-Edition AI features. The
feature logic itself lives under ``app/ee/`` and is **commercial-licensed**
(see ``app/ee/README.md``); this controller is deliberately thin. It:

1. authenticates and gates (feature flag + paid-tier eligibility),
2. runs the existing upload-safety plumbing (magic-byte check, size cap),
3. dispatches by format to the EE engine, and
4. returns a **credit-denominated** response.

The response never carries a model id, token count, or euro cost — so the
operation's cost structure (and thus the margin) stays opaque. The EE engine is
imported **lazily inside the handlers**, so a default self-host build
(``AI_OPERATIONS_ENABLED`` unset) never imports the commercial code and the
AGPL engine stays standalone.

Two-phase flow (the "preview before you commit" requirement):
- ``POST /ai/redact/detect`` → findings to review (free, no credit).
- ``POST /ai/redact/apply``  → the redacted file. Gates on paid-tier eligibility,
  enforces the monthly credit allotment (pre-check, then an atomic charge against
  the persistent ledger), and returns the per-op credit cost in a header.

The CPU-bound parse / detect / redact / verify work runs in ``asyncio.to_thread``
so a single large upload can't block the event loop (event-loop hygiene rule).
AI usage is metered in its own credit unit (``ai_credits_per_month``); it is
deliberately *not* counted against the convert/compress ``api_calls`` quota.

Supported inputs: UTF-8 text, DOCX, XLSX. PDF returns 415 by design — safe PDF
redaction must delete the text layer and is a separate, security-critical
checkpoint; we do not ship a fake (cover-only) redaction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, Response

from app.api.deps import require_api_key
from app.api.routes.auth import get_optional_user
from app.core.ai_credits import ai_credits_remaining, charge_ai_credits, enforce_ai_credit_quota
from app.core.audit import record_event as audit_record
from app.core.concurrency import acquire_slot
from app.core.config import settings
from app.core.metrics import increment as metric_increment
from app.core.processing import BLOCKED_MAGIC, actor_id
from app.core.quotas import _MB, get_quota, tier_for
from app.core.rate_limit import limiter
from app.core.utils import safe_download_name
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Text formats handled by the plain-string path. Everything not here and not
# docx/xlsx is rejected explicitly (415) — a binary file like a PDF that happens
# to be ASCII-decodable must not be silently treated as text.
_TEXT_EXTS = {
    "",
    "txt",
    "text",
    "md",
    "markdown",
    "csv",
    "tsv",
    "log",
    "json",
    "xml",
    "html",
    "htm",
    "yaml",
    "yml",
    "ini",
}


def _unsupported_format() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Unsupported format. Supported: UTF-8 text, DOCX, XLSX.",
        headers={"X-FileMorph-Error-Code": "unsupported_format"},
    )


def _require_ai_enabled() -> None:
    """Inert-without-config gate — mirrors billing's ``_stripe_enabled``."""
    if not settings.ai_operations_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI operations are not available on this deployment.",
            headers={"X-FileMorph-Error-Code": "ai_unavailable"},
        )


def _require_paid_tier(tier: str) -> None:
    """Paid-only gate: AI operations are a commercial add-on, not a free feature."""
    if tier not in settings.ai_eligible_tiers_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI operations require a paid plan.",
            headers={"X-FileMorph-Error-Code": "ai_plan_required"},
        )


def _ext(filename: str | None) -> str:
    return Path(filename or "").suffix.lstrip(".").lower()


def _parse_entity_types(raw: str, valid: tuple[str, ...]) -> tuple[str, ...] | None:
    """Parse the comma-separated entity-type filter. Empty → None (= all types)."""
    if not raw.strip():
        return None
    requested = [t.strip().upper() for t in raw.split(",") if t.strip()]
    unknown = [t for t in requested if t not in valid]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown entity type(s): {', '.join(unknown)}",
            headers={"X-FileMorph-Error-Code": "unknown_entity_type"},
        )
    return tuple(requested)


async def _read_validated_bytes(file: UploadFile, quota) -> bytes:
    """Read the upload and apply the shared upload-safety plumbing (size cap,
    magic-byte deny-list) — same guards as the converters."""
    data = await file.read()
    if len(data) > quota.max_file_size_bytes:
        limit_mb = quota.max_file_size_bytes // _MB
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File too large ({limit_mb} MB max for your plan).",
            headers={"X-FileMorph-Error-Code": "input_too_large"},
        )
    if any(data[:16].startswith(sig) for sig in BLOCKED_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File type not permitted."
        )
    return data


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported format. Supported: UTF-8 text, DOCX, XLSX.",
            headers={"X-FileMorph-Error-Code": "unsupported_format"},
        ) from None


def _text_findings(text: str, spans) -> list[dict]:
    out = []
    for s in spans:
        line = text.count("\n", 0, s.start) + 1
        out.append(
            {
                "entity_type": s.entity_type,
                "value": s.value,
                "location": f"Zeile {line}",
                "confidence": s.confidence,
            }
        )
    return out


@router.post(
    "/ai/redact/detect",
    tags=["AI"],
    dependencies=[Depends(require_api_key)],
    summary="Detect PII in a file (free findings preview)",
    description=(
        "Phase 1 of redaction: scan UTF-8 text, DOCX or XLSX for structured PII "
        "(IBAN, email, phone, IPv4, credit-card) and return the findings to review. "
        "Free, no credit charged. Returns 503 when AI operations are not enabled on "
        "this deployment."
    ),
)
@limiter.limit("20/minute")
async def redact_detect(
    request: Request,
    file: UploadFile,
    entity_types: str = Form("", description="Comma-separated types to scan for; empty = all."),
    user: User | None = Depends(get_optional_user),
) -> Response:
    """Phase 1: find PII so the user can review it before committing.

    Free and open to anonymous / free-tier users — the findings preview is the
    hook that leads to the paid ``apply``, and it makes the /redact page a real,
    usable (indexable) tool rather than a paywall. Still guarded by the inert
    feature gate, the rate limit, the magic-byte check and the per-tier size cap;
    only ``apply`` is paid-tier-gated.
    """
    _require_ai_enabled()
    tier = tier_for(user)
    async with acquire_slot(actor_id=actor_id(request, user), tier=tier):
        # Lazy, commercial: only imported once the feature is enabled + allowed.
        from app.ee.ai_ops import ENTITY_TYPES, detect

        quota = get_quota(tier)
        data = await _read_validated_bytes(file, quota)
        types = _parse_entity_types(entity_types, ENTITY_TYPES)
        ext = _ext(file.filename)

        if ext == "docx":
            from app.ee.ai_ops.formats import detect_docx

            findings = await _guarded(detect_docx, data, types)
        elif ext == "xlsx":
            from app.ee.ai_ops.formats import detect_xlsx

            findings = await _guarded(detect_xlsx, data, types)
        elif ext in _TEXT_EXTS:
            text = _decode_text(data)
            spans = await asyncio.to_thread(detect, text, types)
            findings = _text_findings(text, spans)
        else:
            raise _unsupported_format()

        # Credit-denominated response — no model, no tokens, no euro cost.
        return JSONResponse(
            {
                "findings": findings,
                "count": len(findings),
                "credits_estimate": settings.ai_credit_cost_redact,
                "credits_remaining": await ai_credits_remaining(user),
            }
        )


@router.post(
    "/ai/redact/apply",
    tags=["AI"],
    dependencies=[Depends(require_api_key)],
    summary="Produce the redacted file (paid, credit-metered)",
    description=(
        "Phase 2 of redaction: return the input file with detected PII removed "
        "(replace / mask / remove). Paid-tier only and credit-metered. Fail-closed: "
        "if the output cannot be verified clean, returns 500 with no file. Returns "
        "503 when AI operations are not enabled, 403 for ineligible tiers, 402 when "
        "the monthly credit allotment is exhausted."
    ),
)
@limiter.limit("10/minute")
async def redact_apply(
    request: Request,
    file: UploadFile,
    entity_types: str = Form("", description="Comma-separated types to redact; empty = all."),
    mode: str = Form("replace", description="replace | mask | remove"),
    user: User | None = Depends(get_optional_user),
) -> Response:
    """Phase 2: produce the redacted file. Fail-closed on verification."""
    _require_ai_enabled()
    tier = tier_for(user)
    _require_paid_tier(tier)
    async with acquire_slot(actor_id=actor_id(request, user), tier=tier):
        from app.ee.ai_ops import ENTITY_TYPES, redact_text
        from app.ee.ai_ops.redaction import REDACTION_MODES

        if mode not in REDACTION_MODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown mode {mode!r}. Use one of: {', '.join(REDACTION_MODES)}.",
            )

        quota = get_quota(tier)
        _t0 = time.monotonic()
        data = await _read_validated_bytes(file, quota)
        types = _parse_entity_types(entity_types, ENTITY_TYPES)
        ext = _ext(file.filename)

        # Paid-only credit gate: refuse before doing work if this op would
        # exceed the monthly allotment (no-op for anonymous / unlimited / no DB).
        await enforce_ai_credit_quota(user, settings.ai_credit_cost_redact)

        if ext == "docx":
            from app.ee.ai_ops.formats import redact_docx

            fr = await _guarded(redact_docx, data, types, mode)
            out_bytes, entities = fr.data, fr.entities_redacted
            verification_passed, residual_count = fr.verification_passed, fr.residual_count
            out_ext, media = "docx", _DOCX_MIME
        elif ext == "xlsx":
            from app.ee.ai_ops.formats import redact_xlsx

            fr = await _guarded(redact_xlsx, data, types, mode)
            out_bytes, entities = fr.data, fr.entities_redacted
            verification_passed, residual_count = fr.verification_passed, fr.residual_count
            out_ext, media = "xlsx", _XLSX_MIME
        elif ext in _TEXT_EXTS:
            text = _decode_text(data)
            res = await asyncio.to_thread(redact_text, text, types, mode)
            out_bytes, entities = res.text.encode("utf-8"), res.entities_redacted
            verification_passed, residual_count = res.verification_passed, len(res.residual)
            out_ext, media = "txt", "text/plain; charset=utf-8"
        else:
            raise _unsupported_format()

        # Fail-closed: a residual match means a bug, not user error. Never ship
        # a half-redacted document; log the COUNT only, never the values.
        if not verification_passed:
            logger.error(
                "ai redaction verification failed",
                extra={
                    "operation": "ai-redact",
                    "tier": tier,
                    "format": out_ext,
                    "residual_count": residual_count,
                    "duration_ms": round((time.monotonic() - _t0) * 1000),
                    "success": False,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Redaction could not be verified — no file was produced.",
                headers={"X-FileMorph-Error-Code": "redaction_verification_failed"},
            )

        if len(out_bytes) > quota.output_cap_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Output exceeds the size cap for your plan.",
                headers={"X-FileMorph-Error-Code": "output_cap_exceeded"},
            )

        # Authoritative, atomic charge. The pre-check above fails fast in the
        # common case; this closes the concurrent-request race (raises 402 if a
        # parallel op consumed the last credits first). Only after it succeeds do
        # we emit the success signals and return the file.
        await charge_ai_credits(
            user,
            settings.ai_credit_cost_redact,
            operation="redact",
            model=None,
            used_llm=False,
        )

        original_stem = Path(file.filename or "document").stem
        download_name = safe_download_name(f"{original_stem}.redacted.{out_ext}")

        # Cockpit signal (fire-and-forget) — count only, never content.
        await metric_increment(f"ai-redact.{out_ext}")
        logger.info(
            "ai redaction complete",
            extra={
                "operation": "ai-redact",
                "tier": tier,
                "format": out_ext,
                "entities_redacted": entities,
                "input_size_bytes": len(data),
                "output_size_bytes": len(out_bytes),
                "duration_ms": round((time.monotonic() - _t0) * 1000),
                "success": True,
            },
        )
        # Tamper-evident audit trail (Compliance Edition). Metadata only —
        # never the document content or the detected values.
        await audit_record(
            "ai-redact.success",
            actor_user_id=user.id if user is not None else None,
            actor_ip=request.client.host if request.client else None,
            payload={
                "operation": "redact",
                "format": out_ext,
                "entities_redacted": entities,
                "tier": tier,
                "credits_charged": settings.ai_credit_cost_redact,
            },
        )
        response_headers = {
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "X-FileMorph-AI-Entities-Redacted": str(entities),
            "X-FileMorph-AI-Credits-Cost": str(settings.ai_credit_cost_redact),
        }
        remaining = await ai_credits_remaining(user)
        if remaining is not None:
            response_headers["X-FileMorph-AI-Credits-Remaining"] = str(remaining)
        return Response(content=out_bytes, media_type=media, headers=response_headers)


async def _guarded(func, *args):
    """Run a binary-format handler off the event loop, mapping a parse failure to
    a generic 400.

    The handlers parse / detect / redact / re-verify whole OOXML packages — all
    CPU-bound — so they run in ``asyncio.to_thread`` to keep the event loop free
    (a blocking call here is a single-user DoS). Document-parsing exceptions are
    kept out of the client response (threat-model rule: no exception detail)."""
    from app.ee.ai_ops.formats import DocumentReadError

    try:
        return await asyncio.to_thread(func, *args)
    except DocumentReadError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read the document — it may be corrupt or not a real Office file.",
            headers={"X-FileMorph-Error-Code": "document_unreadable"},
        ) from None
