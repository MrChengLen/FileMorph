# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF page routes — "Morph > Convert" structural ops.

Same-origin endpoints under the existing ``/api/v1`` prefix (no new
cross-origin surface; the response headers a page reads are listed in
``expose_headers`` in ``app/main.py``):

* ``POST /api/v1/pdf/extract`` — form fields ``file`` + ``pages``
  (1-based, e.g. ``"1-3,5"``) → a single PDF containing only those pages.
* ``POST /api/v1/pdf/split`` — form field ``file`` → one single-page PDF
  per page, bundled as a ZIP via :mod:`app.core.batch`.
* ``POST /api/v1/pdf/compress`` — ``file`` + ``target_kb`` → the PDF with
  its images recompressed to fit.
* ``POST /api/v1/pdf/insert`` — ``file`` + ``insert_file`` (a PDF, a
  ``.docx`` or an image) + optional ``after_page`` → the PDF with the second
  file's pages inserted (``app/converters/pdf_insert.py``).

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
from fastapi.responses import Response

from app.api.deps import caller_tier, require_api_key
from app.api.routes.auth import get_optional_user
from app.converters._isolated import TooComplexError, run_isolated
from app.converters.base import EncryptedPdfError, InvalidInputError, OutputTooLargeError
from app.converters.image import _IMAGE_FORMATS
from app.converters.pdf_insert import image_to_pdf, word_to_pdf
from app.converters.pdf_pages import (
    PageSelectionError,
    TooManyPagesError,
    UnreadablePdfError,
    extract_pages,
    split_pdf,
)
from app.core.batch import BatchFileResult, build_batch_zip
from app.core.concurrency import acquire_slot
from app.core.image_hardening import DECOMPRESSION_BOMB
from app.core.metrics import increment as metric_increment
from app.core.observability import record_conversion
from app.core.processing import BLOCKED_MAGIC, actor_id
from app.core.quotas import _MB, file_too_large_message, get_quota, higher_cap_hint
from app.core.rate_limit import limiter
from app.core.responses import TempDirFileResponse
from app.core.usage import enforce_monthly_quota, record_usage
from app.core.utils import safe_download_name
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


def _field_header(field: str | None) -> dict[str, str]:
    """``X-FileMorph-Error-Field`` for a route with more than one upload
    (``/pdf/insert``): the form field the error is about, never a filename."""
    return {"X-FileMorph-Error-Field": field} if field else {}


def _write_upload_and_check_magic(
    upload: UploadFile, input_path: Path, field: str | None = None
) -> int:
    """Stream the upload to disk, run the magic-byte guard, return its size.

    Mirrors the convert route: PE/ELF/shell/PHP prefixes are rejected
    before pypdf ever opens the file. Returns the on-disk byte size.
    """
    with input_path.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    with open(input_path, "rb") as f:
        header = f.read(16)
    if any(header.startswith(sig) for sig in BLOCKED_MAGIC):
        raise HTTPException(
            status_code=400, detail="File type not permitted.", headers=_field_header(field) or None
        )
    return input_path.stat().st_size


def _enforce_input_size(file: UploadFile, quota, tier: str, field: str | None = None) -> None:
    """Tier-based input-size cap — identical semantics to /convert."""
    if file.size is not None and file.size > quota.max_file_size_bytes:
        detail = file_too_large_message(tier, quota.max_file_size_bytes)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=detail,
            headers={"X-FileMorph-Error-Code": "input_too_large", **_field_header(field)},
        )


@router.post("/pdf/extract", tags=["Convert"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def pdf_extract(
    request: Request,
    file: UploadFile,
    pages: str = Form(..., description="1-based pages/ranges, e.g. '1-3,5'"),
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = caller_tier(request, user)
    async with acquire_slot(actor_id=actor_id(request, user, tier), tier=tier):
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
    _enforce_input_size(file, quota, tier)
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
        except (EncryptedPdfError, PageSelectionError) as exc:
            # Caller-safe message already (no pypdf internals). 400 — the
            # client's page selection or PDF was the problem, not the server.
            # The code tells the UI which one, so it doesn't blame the
            # selection for a file without pages or one pypdf can't read,
            # can say so when a password is the reason, and names the page
            # cap instead of the selection syntax for a selection over it.
            logger.info("pdf extract rejected: %s", exc)
            if isinstance(exc, EncryptedPdfError):
                code = exc.error_code
            elif isinstance(exc, UnreadablePdfError):
                code = "invalid_pdf"
            elif isinstance(exc, TooManyPagesError):
                code = "pdf_too_many_pages"
            else:
                code = "invalid_page_selection"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
                headers={"X-FileMorph-Error-Code": code},
            )
        except Exception:
            logger.exception("PDF extract error")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Page extraction failed. Verify your file is a valid PDF.",
            )

        output_disk_size = output_path.stat().st_size
        _enforce_output_cap(output_disk_size, quota, tier)

        download_name = safe_download_name(original_stem, "_pages.pdf")
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

    return TempDirFileResponse(
        output_path,
        tmp_dir=tmp_dir,
        media_type="application/pdf",
        filename=download_name,
    )


@router.post("/pdf/split", tags=["Convert"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def pdf_split(
    request: Request,
    file: UploadFile,
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = caller_tier(request, user)
    async with acquire_slot(actor_id=actor_id(request, user, tier), tier=tier):
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
    _enforce_input_size(file, quota, tier)
    await enforce_monthly_quota(user)

    _t0 = time.monotonic()
    tmp_dir = tempfile.mkdtemp(prefix="fm_")
    try:
        temp_stem = uuid.uuid4().hex
        input_path = Path(tmp_dir) / f"{temp_stem}.pdf"
        input_size_bytes = _write_upload_and_check_magic(file, input_path)

        try:
            # Bandwidth-awareness: the split stops at the tier output cap.
            outputs = await asyncio.to_thread(split_pdf, input_path, quota.output_cap_bytes)
        except HTTPException:
            raise
        except OutputTooLargeError:
            raise _output_cap_error(None, quota, tier) from None
        except (EncryptedPdfError, PageSelectionError) as exc:
            logger.info("pdf split rejected: %s", exc)
            # A PDF over the page cap is valid; invalid_pdf would make the UI
            # call it unreadable.
            if isinstance(exc, EncryptedPdfError):
                code = exc.error_code
            elif isinstance(exc, TooManyPagesError):
                code = "pdf_too_many_pages"
            else:
                code = "invalid_pdf"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
                headers={"X-FileMorph-Error-Code": code},
            )
        except Exception:
            logger.exception("PDF split error")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Split failed. Verify your file is a valid PDF.",
            )

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
    download_name = safe_download_name(Path(file.filename or "result").stem, "_pages.zip")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


_EXTRACT_LESS = "Extract a smaller page range."


def _enforce_output_cap(output_size: int, quota, tier: str, next_step: str = _EXTRACT_LESS) -> None:
    """Reject before streaming if the output exceeds the tier bandwidth cap."""
    if output_size > quota.output_cap_bytes:
        raise _output_cap_error(output_size, quota, tier, next_step)


def _output_cap_error(
    output_size: int | None, quota, tier: str, next_step: str = _EXTRACT_LESS
) -> HTTPException:
    """The output-cap 413. ``None``: the split stopped at the cap, so the full
    size is unknown. ``next_step`` names the free way under the cap."""
    cap_mb = quota.output_cap_bytes // _MB
    if output_size is None:
        too_large = f"Output too large (over the {cap_mb} MB cap)."
    else:
        too_large = f"Output too large ({output_size // _MB} MB > {cap_mb} MB cap)."
    hint = f"{next_step} {higher_cap_hint(tier)}"
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"{too_large} {hint}",
        headers={"X-FileMorph-Error-Code": "output_cap_exceeded"},
    )


# Sanity ceiling on the requested target so a typo (``target_kb=99999999``)
# is a clean 400 instead of a pointless full-document compress that can
# never undershoot it. 2 GB comfortably exceeds every tier's input cap.
_MAX_TARGET_KB = 2 * 1024 * 1024  # 2 GB in KB
_TOO_LARGE_TO_COMPRESS = (
    "This PDF is too large or complex to compress in one go. Extract fewer "
    "pages with /api/v1/pdf/extract and compress them in parts."
)


@router.post("/pdf/compress", tags=["Compress"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def pdf_compress(
    request: Request,
    file: UploadFile,
    target_kb: int = Form(
        ...,
        gt=0,
        le=_MAX_TARGET_KB,
        description="Maximum output size in KB. The PDF's embedded images are "
        "recompressed, and scaled down if needed, to fit; text/vector content and "
        "the layout are preserved.",
    ),
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = caller_tier(request, user)
    async with acquire_slot(actor_id=actor_id(request, user, tier), tier=tier):
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
    _enforce_input_size(file, quota, tier)

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
                f"{higher_cap_hint(tier)}"
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
            # pikepdf parse + Pillow re-encode in a child process with memory
            # and time limits (app/converters/_isolated.py), waited for off
            # the event loop.
            result = await asyncio.to_thread(
                run_isolated,
                "pdf-compress",
                too_large=_TOO_LARGE_TO_COMPRESS,
                tmp_dir=Path(tmp_dir),
                input_path=input_path,
                output_path=output_path,
                target_bytes=target_bytes,
            )
        except HTTPException:
            raise
        except EncryptedPdfError as exc:
            logger.info("pdf compress rejected: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
                headers={"X-FileMorph-Error-Code": exc.error_code},
            )
        except InvalidInputError as exc:
            logger.info("pdf compress rejected: %s", exc)
            # Past the child's memory, time or file size limits the code is its own, so
            # the compress page can link on to the extract tool.
            code = "pdf_too_complex" if isinstance(exc, TooComplexError) else "invalid_input"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
                headers={"X-FileMorph-Error-Code": code},
            )
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
        _enforce_output_cap(output_disk_size, quota, tier)

        download_name = safe_download_name(original_stem, "_compressed.pdf")
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
                "image_scale": result["image_scale"],
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
    if result["image_scale"] is not None:
        # The images were scaled down to fit: ``scaled=<percent>`` of their
        # former resolution.
        percent = max(1, round(result["image_scale"] * 100))
        response_headers["X-FileMorph-Warnings"] = f"scaled={percent}"
    return TempDirFileResponse(
        output_path,
        tmp_dir=tmp_dir,
        media_type="application/pdf",
        filename=download_name,
        headers=response_headers,
    )


# ── Insert ───────────────────────────────────────────────────────────────────

_TOO_COMPLEX_TO_INSERT = (
    "These files are too large or complex to combine in one go. Extract the part "
    "of the PDF you need with /api/v1/pdf/extract and insert into it, or compress "
    "the files first."
)
# Word formats LibreOffice would read, but the insertion takes only .docx: the
# message says how to get there.
_OTHER_DOCUMENT_FORMATS = {"doc", "odt", "rtf", "pages", "wps"}
_INSERT_TYPES = "Insert a PDF, a Word file (.docx) or an image (JPG, PNG, HEIC, WebP, …)."
_COMPRESS_FIRST = "Compress the PDF or the file to insert first."
_INSERT_FIELDS = ("file", "insert_file", "after_page")


# What /pdf/insert takes, by extension; the page offers the same list.
INSERT_FORMATS = ("pdf", "docx", *_IMAGE_FORMATS)


def _insert_kind(filename: str | None) -> str | None:
    """``pdf``, ``docx`` or ``image`` for a file the insertion takes, by its
    extension; ``None`` for any other."""
    ext = Path(filename or "").suffix.lstrip(".").lower()
    if ext not in INSERT_FORMATS:
        return None
    return ext if ext in ("pdf", "docx") else "image"


def _field_error(code: str, field: str, detail: str, **headers: str) -> HTTPException:
    """The 400 for an input the insertion can't use; ``field`` names the form
    field, so the page can show the error there."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
        headers={"X-FileMorph-Error-Code": code, "X-FileMorph-Error-Field": field, **headers},
    )


@router.post("/pdf/insert", tags=["Convert"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def pdf_insert(
    request: Request,
    file: UploadFile,
    insert_file: UploadFile,
    after_page: int | None = Form(
        None,
        ge=0,
        description="Insert after this page (1-based); 0 inserts at the start. "
        "Leave it out to insert at the end.",
    ),
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = caller_tier(request, user)
    async with acquire_slot(actor_id=actor_id(request, user, tier), tier=tier):
        return await _do_insert(request, file, insert_file, after_page, user, tier)


async def _do_insert(
    request: Request,
    file: UploadFile,
    insert_file: UploadFile,
    after_page: int | None,
    user: User | None,
    tier: str,
) -> Response:
    if Path(file.filename or "").suffix.lstrip(".").lower() != "pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Inserting pages requires a PDF to insert them into.",
            headers={"X-FileMorph-Error-Field": "file"},
        )
    kind = _insert_kind(insert_file.filename)
    if kind is None:
        ext = Path(insert_file.filename or "").suffix.lstrip(".").lower()
        detail = (
            "Only Word files in the .docx format can be inserted. Save the document as "
            ".docx or as a PDF first."
            if ext in _OTHER_DOCUMENT_FORMATS
            else f"This file type can't be inserted. {_INSERT_TYPES}"
        )
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=detail,
            headers={
                "X-FileMorph-Error-Code": "unsupported_format",
                "X-FileMorph-Error-Field": "insert_file",
            },
        )

    quota = get_quota(tier)
    _enforce_input_size(file, quota, tier, field="file")
    _enforce_input_size(insert_file, quota, tier, field="insert_file")
    await enforce_monthly_quota(user)

    original_stem = Path(file.filename or "result").stem
    _t0 = time.monotonic()
    tmp_dir = tempfile.mkdtemp(prefix="fm_")
    try:
        temp_stem = uuid.uuid4().hex
        base_path = Path(tmp_dir) / f"{temp_stem}.pdf"
        # The extension is one _insert_kind accepted; the stem stays a UUID.
        insert_ext = Path(insert_file.filename or "").suffix.lstrip(".").lower()
        insert_path = Path(tmp_dir) / f"{temp_stem}.insert.{insert_ext}"
        insert_pdf = insert_path if kind == "pdf" else Path(tmp_dir) / f"{temp_stem}.insert.pdf"
        output_path = Path(tmp_dir) / f"{temp_stem}.out.pdf"
        base_size = _write_upload_and_check_magic(file, base_path, field="file")
        insert_size = _write_upload_and_check_magic(insert_file, insert_path, field="insert_file")

        try:
            # The file to insert as a PDF, in the app process like /convert —
            # before the child reads the PDF and checks the position, so a
            # mistyped page costs a Word file its LibreOffice run: the price
            # of reading no PDF here.
            # One image page is metadata-stripped and turned upright like
            # every image conversion; insert_pages fits it to its neighbour.
            if kind == "image":
                await asyncio.to_thread(image_to_pdf, insert_path, insert_pdf)
            elif kind == "docx":
                await asyncio.to_thread(word_to_pdf, insert_path, insert_pdf)
        except DECOMPRESSION_BOMB:
            logger.warning("pdf insert: decompression bomb rejected")
            raise _field_error(
                "decompression_bomb",
                "insert_file",
                "Image dimensions exceed safety limits — decoding would use "
                "excessive memory. Reduce the image size and retry.",
            ) from None
        except InvalidInputError as exc:
            logger.info("pdf insert rejected (insert_file): %s", exc)
            raise _field_error(
                getattr(exc, "error_code", "invalid_input"), "insert_file", str(exc)
            ) from None

        try:
            # pypdf reads both PDFs, checks the position and merges the pages
            # in a child process with memory and time limits, waited for off
            # the event loop: no PDF is read in the app process.
            result = await asyncio.to_thread(
                run_isolated,
                "pdf-insert",
                too_large=_TOO_COMPLEX_TO_INSERT,
                tmp_dir=Path(tmp_dir),
                base_path=base_path,
                insert_path=insert_pdf,
                output_path=output_path,
                after_page=after_page,
                kind=kind,
                max_output_bytes=quota.output_cap_bytes,
            )
        except OutputTooLargeError:
            raise _output_cap_error(None, quota, tier, _COMPRESS_FIRST) from None
        except InvalidInputError as exc:
            # Damage that only showed while copying, or past the child's
            # limits. The code says which; the field can't.
            logger.info("pdf insert rejected: %s", exc)
            if isinstance(exc, TooComplexError):
                code = "pdf_too_complex"
            else:
                code = getattr(exc, "error_code", "invalid_pdf")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
                headers={"X-FileMorph-Error-Code": code},
            ) from None
        except Exception:
            # security.md: no pypdf internals to the client. Like
            # /pdf/compress, a PDF that breaks the merge is a damaged one: 400.
            logger.exception("PDF insert error")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inserting the pages failed. Verify both files are valid.",
                headers={"X-FileMorph-Error-Code": "invalid_pdf"},
            ) from None
        refused = result.get("refused")
        if refused is not None:
            # Data from the sandboxed child goes into headers and logs: only
            # a known field and a plain code.
            if (
                refused.get("field") not in _INSERT_FIELDS
                or not str(refused.get("code", "")).isidentifier()
            ):
                logger.warning("pdf insert: unexpected refusal from the child")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Inserting the pages failed. Verify both files are valid.",
                    headers={"X-FileMorph-Error-Code": "invalid_pdf"},
                )
            logger.info("pdf insert rejected (%s): %s", refused["field"], refused["code"])
            extra = {}
            if "page_count" in refused:
                extra["X-FileMorph-Page-Count"] = str(refused["page_count"])
            raise _field_error(refused["code"], refused["field"], refused["message"], **extra)
        # Only the result is needed to answer; the inputs go now.
        for path in (base_path, insert_path, insert_pdf):
            path.unlink(missing_ok=True)

        output_disk_size = output_path.stat().st_size
        _enforce_output_cap(output_disk_size, quota, tier, _COMPRESS_FIRST)

        download_name = safe_download_name(original_stem, "_inserted.pdf")
        duration_ms = round((time.monotonic() - _t0) * 1000)
        input_size_bytes = base_size + insert_size
        logger.info(
            "pdf insert complete",
            extra={
                "operation": "pdf_insert",
                "tier": tier,
                "src_format": "pdf",
                "tgt_format": "pdf",
                "insert_format": insert_ext,
                "input_size_bytes": input_size_bytes,
                "output_size_bytes": output_disk_size,
                "inserted_pages": result["inserted_pages"],
                "pages": result["page_count"],
                "duration_ms": duration_ms,
                "success": True,
            },
        )
        await metric_increment("pdf.insert")
        record_conversion("pdf_insert", "pdf", "pdf", "success")
        await record_usage(
            user_id=user.id if user is not None else None,
            api_key_id=None,
            endpoint="pdf/insert",
            file_size_bytes=input_size_bytes,
            duration_ms=duration_ms,
        )
    except HTTPException:
        await metric_increment("failures.pdf_insert")
        record_conversion("pdf_insert", "pdf", "pdf", "failure")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return TempDirFileResponse(
        output_path,
        tmp_dir=tmp_dir,
        media_type="application/pdf",
        filename=download_name,
        headers={
            "X-FileMorph-Inserted-Pages": str(result["inserted_pages"]),
            "X-FileMorph-Page-Count": str(result["page_count"]),
        },
    )
