# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF page-extract + split routes — a "Morph > Convert" structural op.

Two same-origin endpoints under the existing ``/api/v1`` prefix (no new
cross-origin surface, so the network-quadruple-check is a no-op — see the
module-level note in the PR report):

* ``POST /api/v1/pdf/extract`` — form fields ``file`` + ``pages``
  (1-based, e.g. ``"1-3,5"``) → a single PDF containing only those pages.
* ``POST /api/v1/pdf/split`` — form field ``file`` → one single-page PDF
  per page, bundled as a ZIP via :mod:`app.core.batch`.

Why a dedicated route instead of riding ``/convert``
----------------------------------------------------
The shared ``/convert`` route only threads ``target_format`` + ``quality``
into a converter and always returns a single ``application/octet-stream``
file. Extract needs a ``pages`` parameter that would be meaningless for
every other format pair, and split returns a ``application/zip`` — both a
poor fit for that hot, security-sensitive shared surface. A small
dedicated route keeps the convert param-flow untouched while reusing the
same hardening primitives (magic-byte guard, tier caps, output cap,
``asyncio.to_thread`` offload, UUID temp dir, generic errors, concurrency
slot, monthly quota, structured logging).

The engine (``app/converters/pdf_pages.py``) is a registered ``(pdf, pdf)``
converter, so the extract logic stays a registry citizen and is
unit-testable in isolation.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from app.api.deps import require_api_key
from app.api.routes.auth import get_optional_user
from app.compressors.pdf import compress_pdf_to_target
from app.converters.pdf_pages import (
    PageSelectionError,
    extract_pages,
    split_pdf,
)
from app.core.batch import BatchFileResult, build_batch_zip
from app.core.concurrency import acquire_slot
from app.core.metrics import increment as metric_increment
from app.core.observability import record_conversion
from app.core.processing import BLOCKED_MAGIC, actor_id
from app.core.quotas import _MB, get_quota, tier_for
from app.core.rate_limit import limiter
from app.core.usage import enforce_monthly_quota, record_usage
from app.core.utils import safe_download_name
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


def _write_upload_and_check_magic(upload: UploadFile, input_path: Path) -> int:
    """Stream the upload to disk, run the magic-byte guard, return its size.

    Mirrors the convert route: PE/ELF/shell/PHP prefixes are rejected
    before pypdf ever opens the file. Returns the on-disk byte size.
    """
    with input_path.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    with open(input_path, "rb") as f:
        header = f.read(16)
    if any(header.startswith(sig) for sig in BLOCKED_MAGIC):
        raise HTTPException(status_code=400, detail="File type not permitted.")
    return input_path.stat().st_size


def _enforce_input_size(file: UploadFile, quota, user: User | None) -> None:
    """Tier-based input-size cap — identical semantics to /convert."""
    if file.size is not None and file.size > quota.max_file_size_bytes:
        limit_mb = quota.max_file_size_bytes // _MB
        if user is None:
            detail = (
                f"File too large ({limit_mb} MB max for anonymous). "
                "Register free to upload larger files."
            )
        else:
            detail = f"File too large ({limit_mb} MB max for your plan). Upgrade for larger files."
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=detail,
            headers={"X-FileMorph-Error-Code": "input_too_large"},
        )


@router.post("/pdf/extract", tags=["Convert"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def pdf_extract(
    request: Request,
    file: UploadFile,
    pages: str = Form(..., description="1-based pages/ranges, e.g. '1-3,5'"),
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = tier_for(user)
    async with acquire_slot(actor_id=actor_id(request, user), tier=tier):
        return await _do_extract(request, file, pages, user, tier)


async def _do_extract(
    request: Request,
    file: UploadFile,
    pages: str,
    user: User | None,
    tier: str,
) -> Response:
    src_ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if src_ext != "pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Page extraction requires a PDF input.",
        )

    quota = get_quota(tier)
    _enforce_input_size(file, quota, user)
    await enforce_monthly_quota(user)

    original_stem = Path(file.filename or "result").stem
    _t0 = time.monotonic()
    tmp_dir = tempfile.mkdtemp(prefix="fm_")
    try:
        temp_stem = uuid.uuid4().hex
        input_path = Path(tmp_dir) / f"{temp_stem}.pdf"
        output_path = Path(tmp_dir) / f"{temp_stem}.out.pdf"
        input_size_bytes = _write_upload_and_check_magic(file, input_path)

        try:
            # pypdf parse + write off the event loop (sync C-accelerated).
            await asyncio.to_thread(extract_pages, input_path, output_path, pages)
        except HTTPException:
            raise
        except PageSelectionError as exc:
            # Caller-safe message already (no pypdf internals). 400 — the
            # client's page selection or PDF was the problem, not the server.
            logger.info("pdf extract rejected: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
                headers={"X-FileMorph-Error-Code": "invalid_page_selection"},
            )
        except Exception:
            logger.exception("PDF extract error")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Page extraction failed. Verify your file is a valid PDF.",
            )

        output_disk_size = output_path.stat().st_size
        _enforce_output_cap(output_disk_size, quota, user)

        download_name = safe_download_name(f"{original_stem}_pages.pdf")
        duration_ms = round((time.monotonic() - _t0) * 1000)
        logger.info(
            "pdf extract complete",
            extra={
                "operation": "pdf_extract",
                "tier": tier,
                "src_format": "pdf",
                "tgt_format": "pdf",
                "input_size_bytes": input_size_bytes,
                "output_size_bytes": output_disk_size,
                "duration_ms": duration_ms,
                "success": True,
            },
        )
        await metric_increment("pdf.extract")
        record_conversion("pdf_extract", "pdf", "pdf", "success")
        await record_usage(
            user_id=user.id if user is not None else None,
            api_key_id=None,
            endpoint="pdf/extract",
            file_size_bytes=input_size_bytes,
            duration_ms=duration_ms,
        )
    except HTTPException:
        await metric_increment("failures.pdf_extract")
        record_conversion("pdf_extract", "pdf", "pdf", "failure")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=download_name,
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )


@router.post("/pdf/split", tags=["Convert"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def pdf_split(
    request: Request,
    file: UploadFile,
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = tier_for(user)
    async with acquire_slot(actor_id=actor_id(request, user), tier=tier):
        return await _do_split(request, file, user, tier)


async def _do_split(
    request: Request,
    file: UploadFile,
    user: User | None,
    tier: str,
) -> Response:
    src_ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if src_ext != "pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Splitting requires a PDF input.",
        )

    quota = get_quota(tier)
    _enforce_input_size(file, quota, user)
    await enforce_monthly_quota(user)

    _t0 = time.monotonic()
    tmp_dir = tempfile.mkdtemp(prefix="fm_")
    try:
        temp_stem = uuid.uuid4().hex
        input_path = Path(tmp_dir) / f"{temp_stem}.pdf"
        input_size_bytes = _write_upload_and_check_magic(file, input_path)

        try:
            outputs = await asyncio.to_thread(split_pdf, input_path)
        except HTTPException:
            raise
        except PageSelectionError as exc:
            logger.info("pdf split rejected: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
                headers={"X-FileMorph-Error-Code": "invalid_pdf"},
            )
        except Exception:
            logger.exception("PDF split error")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Split failed. Verify your file is a valid PDF.",
            )

        # Bandwidth-awareness: the assembled ZIP must respect the tier
        # output cap just like a single conversion would. Sum the page
        # bytes before building the ZIP so a pathological many-page PDF is
        # rejected without buffering the archive.
        total_out = sum(len(b) for _, b in outputs)
        _enforce_output_cap(total_out, quota, user)

        results = [
            BatchFileResult(
                name=name,
                status="ok",
                size_in=input_size_bytes if i == 0 else 0,
                size_out=len(content),
                content=content,
            )
            for i, (name, content) in enumerate(outputs)
        ]
        duration_ms = round((time.monotonic() - _t0) * 1000)
        zip_bytes, summary = build_batch_zip(
            results, operation="pdf_split", duration_ms=duration_ms
        )

        logger.info(
            "pdf split complete",
            extra={
                "operation": "pdf_split",
                "tier": tier,
                "src_format": "pdf",
                "tgt_format": "zip",
                "input_size_bytes": input_size_bytes,
                "output_size_bytes": len(zip_bytes),
                "pages": len(outputs),
                "duration_ms": duration_ms,
                "success": True,
            },
        )
        await metric_increment("pdf.split")
        record_conversion("pdf_split", "pdf", "zip", "success")
        await record_usage(
            user_id=user.id if user is not None else None,
            api_key_id=None,
            endpoint="pdf/split",
            file_size_bytes=input_size_bytes,
            duration_ms=duration_ms,
        )
    except HTTPException:
        await metric_increment("failures.pdf_split")
        record_conversion("pdf_split", "pdf", "zip", "failure")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # ZIP is fully built in memory; the temp dir only held the input PDF.
    shutil.rmtree(tmp_dir, ignore_errors=True)
    download_name = safe_download_name(f"{Path(file.filename or 'result').stem}_pages.zip")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


def _enforce_output_cap(output_size: int, quota, user: User | None) -> None:
    """Reject before streaming if the output exceeds the tier bandwidth cap."""
    if output_size > quota.output_cap_bytes:
        cap_mb = quota.output_cap_bytes // _MB
        out_mb = output_size // _MB
        hint = (
            "Extract a smaller page range or register for a higher cap."
            if user is None
            else "Extract a smaller page range or upgrade your plan."
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Output too large ({out_mb} MB > {cap_mb} MB cap). {hint}",
            headers={"X-FileMorph-Error-Code": "output_cap_exceeded"},
        )


# Sanity ceiling on the requested target so a typo (``target_kb=99999999``)
# is a clean 400 instead of a pointless full-document compress that can
# never undershoot it. 2 GB comfortably exceeds every tier's input cap.
_MAX_TARGET_KB = 2 * 1024 * 1024  # 2 GB in KB


@router.post("/pdf/compress", tags=["Compress"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def pdf_compress(
    request: Request,
    file: UploadFile,
    target_kb: int = Form(
        ...,
        gt=0,
        le=_MAX_TARGET_KB,
        description="Target output size in KB. The PDF's embedded images are "
        "recompressed toward this budget; text/vector content is preserved.",
    ),
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = tier_for(user)
    async with acquire_slot(actor_id=actor_id(request, user), tier=tier):
        return await _do_compress(request, file, target_kb, user, tier)


async def _do_compress(
    request: Request,
    file: UploadFile,
    target_kb: int,
    user: User | None,
    tier: str,
) -> Response:
    src_ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if src_ext != "pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="PDF compression requires a PDF input.",
        )

    quota = get_quota(tier)
    _enforce_input_size(file, quota, user)

    target_bytes = target_kb * 1024
    # Fence the requested target against the tier output cap *before* any
    # work — a caller asking for more than their cap allows can't get it,
    # and we shouldn't burn an event-loop thread proving it (mirrors the
    # image compress-to-target gate in app/api/routes/compress.py).
    if target_bytes > quota.output_cap_bytes:
        cap_kb = quota.output_cap_bytes // 1024
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Target size {target_kb} KB exceeds tier output cap of {cap_kb} KB. "
                "Upgrade your plan for larger outputs."
            ),
            headers={"X-FileMorph-Error-Code": "target_size_exceeds_cap"},
        )

    await enforce_monthly_quota(user)

    original_stem = Path(file.filename or "result").stem
    _t0 = time.monotonic()
    tmp_dir = tempfile.mkdtemp(prefix="fm_")
    try:
        temp_stem = uuid.uuid4().hex
        input_path = Path(tmp_dir) / f"{temp_stem}.pdf"
        output_path = Path(tmp_dir) / f"{temp_stem}.out.pdf"
        input_size_bytes = _write_upload_and_check_magic(file, input_path)

        try:
            # pikepdf parse + Pillow re-encode off the event loop (sync,
            # C-accelerated, and CPU-heavy for image-rich PDFs).
            result = await asyncio.to_thread(
                compress_pdf_to_target,
                input_path,
                output_path,
                target_bytes=target_bytes,
            )
        except HTTPException:
            raise
        except Exception:
            # security.md: no pikepdf/Pillow internals to the client — a
            # malformed PDF or undecodable image surfaces as a generic 400.
            logger.exception("PDF compress error")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF compression failed. Verify your file is a valid PDF.",
                headers={"X-FileMorph-Error-Code": "invalid_pdf"},
            )

        output_disk_size = output_path.stat().st_size
        # The engine targets ``target_bytes`` (already ≤ cap), but a
        # text-heavy PDF can legitimately come out larger than the target
        # (nothing to recompress). Keep the same hard bandwidth backstop
        # the other routes use so a pathological output can never exceed
        # the tier cap.
        _enforce_output_cap(output_disk_size, quota, user)

        download_name = safe_download_name(f"{original_stem}_compressed.pdf")
        duration_ms = round((time.monotonic() - _t0) * 1000)
        logger.info(
            "pdf compress complete",
            extra={
                "operation": "pdf_compress",
                "tier": tier,
                "src_format": "pdf",
                "tgt_format": "pdf",
                "input_size_bytes": input_size_bytes,
                "output_size_bytes": output_disk_size,
                "target_kb": target_kb,
                "final_quality": result["final_quality"],
                "achieved_size_bytes": result["achieved_bytes"],
                "recompressible_images": result["recompressible_images"],
                "iterations": result["iterations"],
                "converged": result["converged"],
                "duration_ms": duration_ms,
                "success": True,
            },
        )
        await metric_increment("pdf.compress")
        record_conversion("pdf_compress", "pdf", "pdf", "success")
        await record_usage(
            user_id=user.id if user is not None else None,
            api_key_id=None,
            endpoint="pdf/compress",
            file_size_bytes=input_size_bytes,
            duration_ms=duration_ms,
        )
    except HTTPException:
        await metric_increment("failures.pdf_compress")
        record_conversion("pdf_compress", "pdf", "pdf", "failure")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Expose the size/convergence outcome so the cross-origin client can
    # tell the user "shrunk to N KB" or "already optimal — no large images
    # to compress" without re-measuring. (These are same-origin today; if
    # /api ever moves cross-origin they must be added to expose_headers —
    # see .claude/rules/workflow-lessons.md network-quadruple-check.)
    response_headers = {
        "X-FileMorph-Achieved-Bytes": str(result["achieved_bytes"]),
        "X-FileMorph-Converged": "true" if result["converged"] else "false",
        "X-FileMorph-Recompressible-Images": str(result["recompressible_images"]),
    }
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=download_name,
        headers=response_headers,
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )
