# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, Response

from app.api.deps import caller_tier, require_api_key
from app.api.routes.auth import get_optional_user
from app.compressors.image import (
    _SUPPORTED_FORMATS as IMAGE_FMTS,
    TARGET_SIZE_FORMATS,
    compress_image,
    compress_image_to_target,
)
from app.compressors.video import _SUPPORTED_FORMATS as VIDEO_FMTS
from app.compressors.video import compress_video
from app.converters._ffmpeg import media_time_limit
from app.converters.base import InvalidInputError, OutputTooLargeError
from app.core.audit import record_event as audit_record
from app.core.batch import (
    BatchFileError,
    BatchFileResult,
    batch_error_response,
    batch_summary_headers,
    build_batch_zip,
)
from app.core.concurrency import acquire_slot
from app.core.data_classification import DEFAULT_CLASSIFICATION as DATA_CLASSIFICATION_DEFAULT
from app.core.image_hardening import DECOMPRESSION_BOMB
from app.core.metrics import increment as metric_increment
from app.core.observability import record_conversion
from app.core.processing import BLOCKED_MAGIC, actor_id, sha256_file
from app.core.quotas import (
    _MB,
    file_too_large_message,
    get_quota,
    higher_cap_hint,
    larger_batches_hint,
)
from app.core.rate_limit import limiter
from app.core.responses import TempDirFileResponse
from app.core.usage import enforce_monthly_quota, record_usage
from app.core.utils import safe_download_name
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


def target_notes(result: dict) -> list[str]:
    """``X-FileMorph-Warnings`` tokens for a target-size result.

    ``resized=<w>x<h>``: the image was scaled down to fit the target.
    ``target=missed``: not even the smallest size fits; the output is larger
    than the target.
    """
    notes = []
    if result["resized_to"] is not None:
        notes.append("resized={}x{}".format(*result["resized_to"]))
    if not result["converged"]:
        notes.append("target=missed")
    return notes


@router.post("/compress", tags=["Compress"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def compress_file(
    request: Request,
    file: UploadFile,
    quality: int | None = Form(None, ge=1, le=100, description="Quality 1 (smallest) - 100 (best)"),
    target_size_kb: int | None = Form(
        None,
        ge=5,
        description="Maximum output size in KB. Searches for the best quality that fits and "
        "scales the image down when even the lowest quality doesn't. "
        "Mutually exclusive with quality. JPEG/WebP/AVIF only.",
    ),
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = caller_tier(request, user)
    async with acquire_slot(actor_id=actor_id(request, user, tier), tier=tier):
        with media_time_limit():
            return await _do_compress(request, file, quality, target_size_kb, user, tier)


async def _do_compress(
    request: Request,
    file: UploadFile,
    quality: int | None,
    target_size_kb: int | None,
    user: User | None,
    tier: str,
) -> Response:
    if quality is not None and target_size_kb is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either quality or target_size_kb, not both.",
        )
    effective_quality = 85 if quality is None else quality

    ext = Path(file.filename or "").suffix.lstrip(".").lower()

    if ext not in IMAGE_FMTS and ext not in VIDEO_FMTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Compression not supported for '.{ext}'. Supported: {IMAGE_FMTS + VIDEO_FMTS}",
        )

    # Tier-based file size enforcement (per-tier limits: app/core/quotas.py).
    # ``tier`` is passed in from the wrapper that already acquired the
    # NEU-D.1 concurrency slot — keep it identical so cap-enforcement
    # and capacity-accounting agree on the caller's tier.
    quota = get_quota(tier)
    if file.size is not None and file.size > quota.max_file_size_bytes:
        detail = file_too_large_message(tier, quota.max_file_size_bytes)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=detail,
            headers={"X-FileMorph-Error-Code": "input_too_large"},
        )

    # PR-M: monthly API-call quota gate. See app/core/usage.py.
    await enforce_monthly_quota(user)

    if target_size_kb is not None:
        if ext not in TARGET_SIZE_FORMATS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    "Target-size compression supports only JPEG, WebP and AVIF. "
                    "Use quality= for PNG/TIFF."
                ),
            )
        target_bytes = target_size_kb * 1024
        if target_bytes > quota.output_cap_bytes:
            cap_kb = quota.output_cap_bytes // 1024
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Target size {target_size_kb} KB exceeds tier output cap of {cap_kb} KB. "
                    f"{higher_cap_hint(tier)}"
                ),
                headers={"X-FileMorph-Error-Code": "target_size_exceeds_cap"},
            )

    # GDPR: keep original stem only for Content-Disposition, never as a filesystem path
    original_stem = Path(file.filename or "result").stem

    # A-1 + GDPR: UUID temp names — no PII on disk, no path traversal
    _t0 = time.monotonic()
    tmp_dir = tempfile.mkdtemp(prefix="fm_")
    try:
        temp_stem = uuid.uuid4().hex
        input_path = Path(tmp_dir) / f"{temp_stem}.{ext}"
        output_path = Path(tmp_dir) / f"{temp_stem}_compressed.{ext}"

        with input_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        # The framework's own copy (on disk above 1 MB) goes now, not after the
        # response.
        await file.close()
        input_size_bytes = input_path.stat().st_size

        # A-1: Magic-byte validation
        with open(input_path, "rb") as f:
            header = f.read(16)
        if any(header.startswith(sig) for sig in BLOCKED_MAGIC):
            raise HTTPException(
                status_code=400,
                detail="File type not permitted.",
                headers={"X-FileMorph-Error-Code": "file_type_not_permitted"},
            )

        target_result: dict | None = None
        try:
            # Offload sync FFmpeg / Pillow call to a worker thread so the
            # event-loop keeps serving other requests while we encode.
            if target_size_kb is not None:
                target_result = await asyncio.to_thread(
                    compress_image_to_target,
                    input_path,
                    output_path,
                    target_bytes=target_size_kb * 1024,
                )
            elif ext in IMAGE_FMTS:
                await asyncio.to_thread(
                    compress_image, input_path, output_path, quality=effective_quality
                )
            else:
                await asyncio.to_thread(
                    compress_video,
                    input_path,
                    output_path,
                    quality=effective_quality,
                    max_output_bytes=quota.output_cap_bytes,
                )
        except HTTPException:
            raise
        except OutputTooLargeError:
            output_disk_size = None  # ffmpeg stopped writing at the cap: answered below
        except DECOMPRESSION_BOMB as exc:
            # P3-4: Same hard-reject path as /convert. See app/core/image_hardening.py
            # for the warning-to-error promotion at startup.
            logger.warning("decompression bomb rejected: compress %s (%s)", ext, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Image dimensions exceed safety limits — decoding would "
                    "use excessive memory. Reduce the image size and retry."
                ),
                headers={"X-FileMorph-Error-Code": "decompression_bomb"},
            )
        except InvalidInputError as exc:
            # A problem the user can fix, e.g. an image that can't be read in a
            # supported format. The message is caller-safe; same 400 as /convert.
            logger.info("invalid input rejected: compress %s (%s)", ext, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
                headers={"X-FileMorph-Error-Code": "invalid_input"},
            )
        except Exception:
            # A-3: log the failure server-side (type and traceback; the text only
            # with APP_DEBUG — it can quote the upload), generic message to client
            logger.exception("Compression error for format: %s", ext)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Compression failed. Verify your file is valid and the format is supported.",
                headers={"X-FileMorph-Error-Code": "compress_failed"},
            )
        else:
            output_disk_size = output_path.stat().st_size

        # Only the result is needed to answer; the upload goes now.
        input_path.unlink(missing_ok=True)

        # S1-B: Output-cap check — defensive guard; compression should shrink
        # files, but a pathological input (already-optimized PNG, very-low-bitrate
        # video) may not gain anything, and we still want an upper bound.
        if output_disk_size is None or output_disk_size > quota.output_cap_bytes:
            cap_mb = quota.output_cap_bytes // _MB
            size = (
                f"over the {cap_mb} MB cap"
                if output_disk_size is None
                else f"{output_disk_size // _MB} MB > {cap_mb} MB cap"
            )
            # S4-foundation: count cap-rejections per tier / format so
            # dashboards can see compression-didn't-help hits.
            logger.info(
                "compression rejected",
                extra={
                    "operation": "compress",
                    "reason": "output_cap",
                    "tier": tier,
                    "format": ext,
                    "input_size_bytes": input_size_bytes,
                    "output_size_bytes": output_disk_size,
                    "cap_bytes": quota.output_cap_bytes,
                    "duration_ms": round((time.monotonic() - _t0) * 1000),
                    "success": False,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Output too large ({size}). Lower the quality. {higher_cap_hint(tier)}",
                headers={"X-FileMorph-Error-Code": "output_cap_exceeded"},
            )

        # S3: stream the output from disk instead of buffering into RAM. The
        # response removes the temp dir once it ends, sent in full or cut off
        # (TempDirFileResponse). On any error path below (or above, before this
        # block), the except handler cleans up sync.
        download_name = safe_download_name(original_stem, f"_compressed.{ext}")
        output_size_bytes = output_disk_size
        amplification_ratio = (
            round(output_size_bytes / input_size_bytes, 3) if input_size_bytes > 0 else None
        )
        log_extra = {
            "operation": "compress",
            "tier": tier,
            "format": ext,
            "input_size_bytes": input_size_bytes,
            "output_size_bytes": output_size_bytes,
            "file_size_bytes": output_size_bytes,  # legacy key kept for existing dashboards
            "amplification_ratio": amplification_ratio,
            "duration_ms": round((time.monotonic() - _t0) * 1000),
            "success": True,
        }
        if target_result is not None:
            log_extra.update(
                {
                    "target_size_kb": target_size_kb,
                    "final_quality": target_result["final_quality"],
                    "achieved_size_bytes": target_result["achieved_bytes"],
                    "iterations": target_result["iterations"],
                    "converged": target_result["converged"],
                    "resized_to": target_result["resized_to"],
                }
            )
        logger.info("compression complete", extra=log_extra)
        # S10-lite: per-format counter for the cockpit Analytics view.
        # increment opens its own session so a metrics failure can never
        # corrupt the response (no caller transaction here, but the
        # principle keeps batch / auth integrations safe).
        await metric_increment(f"compress.{ext}")
        # Prometheus mirror — compression keeps the format, so src == tgt.
        record_conversion("compress", ext, ext, "success")
        # NEU-B.2: integrity hash for downstream auditors (eDiscovery,
        # GoBD-archival, beA-Anhang-Trail). Same chunk-streamed SHA-256
        # as in convert.py.
        output_hash = await asyncio.to_thread(sha256_file, output_path)
        await audit_record(
            "compress.success",
            actor_user_id=user.id if user is not None else None,
            payload={
                "format": ext,
                "input_bytes": input_size_bytes,
                "output_bytes": output_size_bytes,
                "output_sha256": output_hash,
                "tier": tier,
                "data_classification": getattr(
                    request.state, "data_classification", DATA_CLASSIFICATION_DEFAULT
                ),
            },
        )
        # PR-M: count this successful compression toward the user's monthly
        # API-call quota. Failed attempts do not count (the audit log still
        # records them; only completed work moves the user toward the limit).
        await record_usage(
            user_id=user.id if user is not None else None,
            api_key_id=None,
            endpoint="compress",
            file_size_bytes=input_size_bytes,
            duration_ms=round((time.monotonic() - _t0) * 1000),
        )
    except HTTPException as exc:
        # Clean up first: with AUDIT_FAIL_CLOSED the audit write below can
        # raise, and nothing after it would run.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # Track compression failures separately from infra so the cockpit
        # has a meaningful failure-rate. The HTTPException still propagates.
        await metric_increment("failures.compress")
        record_conversion("compress", ext, ext, "failure")
        await audit_record(
            "compress.failure",
            actor_user_id=user.id if user is not None else None,
            payload={
                "format": ext,
                "status_code": exc.status_code,
                "data_classification": getattr(
                    request.state, "data_classification", DATA_CLASSIFICATION_DEFAULT
                ),
            },
        )
        raise
    except BaseException:
        # The response takes over the temp dir only once it is returned; clean
        # up synchronously on cancellation / unexpected errors before that.
        # HTTPException is caught above.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    response_headers: dict[str, str] = {"X-Output-SHA256": output_hash}
    if target_result is not None:
        response_headers["X-FileMorph-Achieved-Bytes"] = str(target_result["achieved_bytes"])
        response_headers["X-FileMorph-Final-Quality"] = str(target_result["final_quality"])
        response_headers["X-FileMorph-Converged"] = (
            "true" if target_result["converged"] else "false"
        )
        notes = target_notes(target_result)
        if notes:
            response_headers["X-FileMorph-Warnings"] = ",".join(notes)

    return TempDirFileResponse(
        output_path,
        tmp_dir=tmp_dir,
        media_type="application/octet-stream",
        filename=download_name,
        headers=response_headers,
    )


@router.post("/compress/batch", tags=["Compress"], dependencies=[Depends(require_api_key)])
@limiter.limit("3/minute")
async def compress_batch(
    request: Request,
    files: list[UploadFile] = File(..., description="Files to compress (multi-upload)"),
    quality: int | None = Form(None, ge=1, le=100),
    target_size_kb: int | None = Form(
        None,
        ge=5,
        description="Maximum output size in KB, as for /compress. Applies to all files. "
        "JPEG/WebP/AVIF only.",
    ),
    user: User | None = Depends(get_optional_user),
) -> Response:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded.")

    tier = caller_tier(request, user)
    # NEU-D.1: same one-slot-per-batch policy as convert/batch, and the
    # same shared time limit for its videos.
    async with acquire_slot(actor_id=actor_id(request, user, tier), tier=tier):
        with media_time_limit():
            return await _do_compress_batch(request, files, quality, target_size_kb, user, tier)


async def _do_compress_batch(
    request: Request,
    files: list[UploadFile],
    quality: int | None,
    target_size_kb: int | None,
    user: User | None,
    tier: str,
) -> Response:
    if quality is not None and target_size_kb is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either quality or target_size_kb, not both.",
        )
    effective_quality = 85 if quality is None else quality

    quota = get_quota(tier)
    if len(files) > quota.max_files_per_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Batch size {len(files)} exceeds tier limit of {quota.max_files_per_batch}. "
                f"{larger_batches_hint(tier)}"
            ),
            headers={"X-FileMorph-Error-Code": "batch_too_large"},
        )

    if target_size_kb is not None:
        target_bytes = target_size_kb * 1024
        if target_bytes > quota.output_cap_bytes:
            cap_kb = quota.output_cap_bytes // 1024
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Target size {target_size_kb} KB exceeds tier output cap of {cap_kb} KB. "
                    f"{higher_cap_hint(tier)}"
                ),
                headers={"X-FileMorph-Error-Code": "target_size_exceeds_cap"},
            )

    # PR-M: monthly quota gate before file I/O. One batch = one API call.
    await enforce_monthly_quota(user)

    _t0 = time.monotonic()
    results: list[BatchFileResult] = []
    # Aggregate per-key counts and flush once at the end — one UPSERT per
    # unique key instead of N round-trips for an N-file batch.
    metric_counts: dict[str, int] = {}

    for upload in files:
        original_stem = Path(upload.filename or "result").stem
        ext = Path(upload.filename or "").suffix.lstrip(".").lower()
        size_in = upload.size or 0
        out_name = safe_download_name(original_stem, f"_compressed.{ext}")

        try:
            if not ext:
                raise BatchFileError("Cannot determine format from filename.")
            if ext not in IMAGE_FMTS and ext not in VIDEO_FMTS:
                raise BatchFileError(f"Compression not supported for '.{ext}'.")
            if size_in > quota.max_file_size_bytes:
                raise BatchFileError(file_too_large_message(tier, quota.max_file_size_bytes))

            tmp_dir = tempfile.mkdtemp(prefix="fm_")
            try:
                temp_stem = uuid.uuid4().hex
                input_path = Path(tmp_dir) / f"{temp_stem}.{ext}"
                output_path = Path(tmp_dir) / f"{temp_stem}_compressed.{ext}"

                with input_path.open("wb") as f:
                    shutil.copyfileobj(upload.file, f)
                await upload.close()  # the framework's own copy goes now

                with open(input_path, "rb") as f:
                    header = f.read(16)
                if any(header.startswith(sig) for sig in BLOCKED_MAGIC):
                    raise BatchFileError("File type not permitted.")

                notes: list[str] = []
                if target_size_kb is not None:
                    if ext not in TARGET_SIZE_FORMATS:
                        raise BatchFileError(
                            "Target-size compression supports only JPEG, WebP and AVIF. "
                            "Use quality= for PNG/TIFF."
                        )
                    target_result = await asyncio.to_thread(
                        compress_image_to_target,
                        input_path,
                        output_path,
                        target_bytes=target_size_kb * 1024,
                    )
                    notes = target_notes(target_result)
                elif ext in IMAGE_FMTS:
                    await asyncio.to_thread(
                        compress_image, input_path, output_path, quality=effective_quality
                    )
                else:
                    try:
                        await asyncio.to_thread(
                            compress_video,
                            input_path,
                            output_path,
                            quality=effective_quality,
                            max_output_bytes=quota.output_cap_bytes,
                        )
                    except OutputTooLargeError:  # ffmpeg stopped writing at the cap
                        raise BatchFileError(
                            f"Output too large (over the {quota.output_cap_bytes // _MB} MB "
                            f"cap). Lower the quality. {higher_cap_hint(tier)}"
                        ) from None

                # S1-B: Output-cap check — reject before loading into memory.
                output_disk_size = output_path.stat().st_size
                if output_disk_size > quota.output_cap_bytes:
                    cap_mb = quota.output_cap_bytes // _MB
                    out_mb = output_disk_size // _MB
                    raise BatchFileError(
                        f"Output too large ({out_mb} MB > {cap_mb} MB cap). "
                        f"Lower the quality. {higher_cap_hint(tier)}"
                    )

                content = output_path.read_bytes()
                results.append(
                    BatchFileResult(
                        name=out_name,
                        status="ok",
                        size_in=size_in,
                        size_out=len(content),
                        content=content,
                        notes=notes,
                    )
                )
                key = f"compress.{ext}"
                metric_counts[key] = metric_counts.get(key, 0) + 1
                record_conversion("compress_batch", ext, ext, "success")
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except (BatchFileError, InvalidInputError) as e:
            # Only this route's own messages and fixable input problems a
            # compressor named; a compressor's ValueError (e.g. from Pillow) is
            # logged and reported generically below.
            results.append(
                BatchFileResult(
                    name=out_name, status="error", size_in=size_in, error_message=str(e)
                )
            )
            metric_counts["failures.compress"] = metric_counts.get("failures.compress", 0) + 1
            record_conversion("compress_batch", ext, ext, "failure")
        except Exception:
            logger.exception("Batch compression error on one file")
            results.append(
                BatchFileResult(
                    name=out_name,
                    status="error",
                    size_in=size_in,
                    error_message="Compression failed. Verify the file is valid.",
                )
            )
            metric_counts["failures.compress"] = metric_counts.get("failures.compress", 0) + 1
            record_conversion("compress_batch", ext, ext, "failure")

    for key, count in metric_counts.items():
        await metric_increment(key, by=count)

    duration_ms = round((time.monotonic() - _t0) * 1000)
    zip_bytes, summary = build_batch_zip(results, operation="compress", duration_ms=duration_ms)
    rejected_output_cap = sum(
        1 for r in results if r.status == "error" and "Output too large" in (r.error_message or "")
    )
    logger.info(
        "batch compress complete",
        extra={
            "operation": "compress_batch",
            "tier": tier,
            "rejected_output_cap": rejected_output_cap,
            **summary,
        },
    )

    if summary["succeeded"] == 0:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=batch_error_response(results, summary),
        )

    # PR-M: one row per HTTP call (not per-file inside the batch).
    await record_usage(
        user_id=user.id if user is not None else None,
        api_key_id=None,
        endpoint="compress/batch",
        file_size_bytes=sum(r.size_in for r in results),
        duration_ms=duration_ms,
    )

    response_headers = {"Content-Disposition": 'attachment; filename="filemorph-batch.zip"'}
    # P2-1: see app/api/routes/convert.py — same structured batch summary
    # so the UI can render per-file results without unzipping.
    response_headers.update(batch_summary_headers(results, summary))
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers=response_headers,
    )
