import asyncio
import hashlib
import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.background import BackgroundTask

from app.api.deps import require_api_key
from app.api.routes.auth import get_optional_user
from app.compressors.image import (
    _SUPPORTED_FORMATS as IMAGE_FMTS,
    TARGET_SIZE_FORMATS,
    compress_image,
    compress_image_to_target,
)
from app.compressors.video import _SUPPORTED_FORMATS as VIDEO_FMTS
from app.compressors.video import compress_video
from app.core.audit import record_event as audit_record
from app.core.batch import BatchFileResult, batch_error_response, build_batch_zip
from app.core.concurrency import acquire_slot
from app.core.data_classification import DEFAULT_CLASSIFICATION as DATA_CLASSIFICATION_DEFAULT
from app.core.metrics import increment as metric_increment
from app.core.quotas import _MB, get_quota, tier_for
from app.core.rate_limit import limiter
from app.core.utils import safe_download_name
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

BLOCKED_MAGIC = [b"MZ", b"\x7fELF", b"#!/", b"<?ph"]


def _sha256_file(path: Path, *, chunk_size: int = 64 * 1024) -> str:
    """Streaming SHA-256 over an on-disk file (NEU-B.2). Mirrors the
    helper in ``app/api/routes/convert.py``; kept duplicated rather
    than extracted because it lives at the route boundary and the
    duplication is one helper, not a pattern. If a third caller
    appears, promote to ``app/core/utils.py``."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _actor_id(request: Request, user: User | None) -> str:
    """Stable identity for the per-actor concurrency cap (NEU-D.1).

    Same shape as the helper in ``app/api/routes/convert.py``;
    duplicated rather than extracted while there are only two
    callers. Promote to ``app/core/quotas.py`` (or a new
    ``app/core/identity.py``) when a third route needs it."""
    if user is not None:
        return f"user:{user.id}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


@router.post("/compress", tags=["Compress"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def compress_file(
    request: Request,
    file: UploadFile,
    quality: int | None = Form(None, ge=1, le=100, description="Quality 1 (smallest) - 100 (best)"),
    target_size_kb: int | None = Form(
        None,
        ge=5,
        description="Target output size in KB. Activates binary-search-on-quality. "
        "Mutually exclusive with quality. JPEG/WebP only.",
    ),
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = tier_for(user)
    async with acquire_slot(actor_id=_actor_id(request, user), tier=tier):
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Compression not supported for '.{ext}'. Supported: {IMAGE_FMTS + VIDEO_FMTS}",
        )

    # Tier-based file size enforcement (anonymous: 20 MB, free: 50, pro: 100, business: 500).
    # ``tier`` is passed in from the wrapper that already acquired the
    # NEU-D.1 concurrency slot — keep it identical so cap-enforcement
    # and capacity-accounting agree on the caller's tier.
    quota = get_quota(tier)
    if file.size is not None and file.size > quota.max_file_size_bytes:
        limit_mb = quota.max_file_size_bytes // (1024 * 1024)
        if user is None:
            detail = (
                f"File too large ({limit_mb} MB max for anonymous). "
                "Register free to upload up to 50 MB."
            )
        else:
            detail = f"File too large ({limit_mb} MB max for your plan). Upgrade for larger files."
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=detail)

    if target_size_kb is not None:
        if ext not in TARGET_SIZE_FORMATS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    "Target-size compression supports only JPEG and WebP. "
                    "Use quality= for PNG/TIFF."
                ),
            )
        target_bytes = target_size_kb * 1024
        if target_bytes > quota.output_cap_bytes:
            cap_kb = quota.output_cap_bytes // 1024
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Target size {target_size_kb} KB exceeds tier output cap of {cap_kb} KB. "
                    "Upgrade your plan for larger outputs."
                ),
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
        input_size_bytes = input_path.stat().st_size

        # A-1: Magic-byte validation
        with open(input_path, "rb") as f:
            header = f.read(16)
        if any(header.startswith(sig) for sig in BLOCKED_MAGIC):
            raise HTTPException(status_code=400, detail="File type not permitted.")

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
                    compress_video, input_path, output_path, quality=effective_quality
                )
        except HTTPException:
            raise
        except Exception:
            # A-3: Log full exception server-side, return generic message to client
            logger.exception("Compression error for format: %s", ext)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Compression failed. Verify your file is valid and the format is supported.",
            )

        # S1-B: Output-cap check — defensive guard; compression should shrink
        # files, but a pathological input (already-optimized PNG, very-low-bitrate
        # video) may not gain anything, and we still want an upper bound.
        output_disk_size = output_path.stat().st_size
        if output_disk_size > quota.output_cap_bytes:
            cap_mb = quota.output_cap_bytes // _MB
            out_mb = output_disk_size // _MB
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
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Output too large ({out_mb} MB > {cap_mb} MB cap). "
                    "Lower the quality or upgrade your plan."
                ),
            )

        # S3: stream the output from disk instead of buffering into RAM. The
        # BackgroundTask runs after the response body is fully sent, so temp
        # cleanup is deferred but still guaranteed. On any error path below
        # (or above, before this block), the except handler cleans up sync.
        download_name = safe_download_name(f"{original_stem}_compressed.{ext}")
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
                }
            )
        logger.info("compression complete", extra=log_extra)
        # S10-lite: per-format counter for the cockpit Analytics view.
        # increment opens its own session so a metrics failure can never
        # corrupt the response (no caller transaction here, but the
        # principle keeps batch / auth integrations safe).
        await metric_increment(f"compress.{ext}")
        # NEU-B.2: integrity hash for downstream auditors (eDiscovery,
        # GoBD-archival, beA-Anhang-Trail). Same chunk-streamed SHA-256
        # as in convert.py.
        output_hash = await asyncio.to_thread(_sha256_file, output_path)
        await audit_record(
            "compress.success",
            actor_user_id=user.id if user is not None else None,
            actor_ip=request.client.host if request.client else None,
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
    except HTTPException as exc:
        # Track compression failures separately from infra so the cockpit
        # has a meaningful failure-rate. The HTTPException still propagates.
        await metric_increment("failures.compress")
        await audit_record(
            "compress.failure",
            actor_user_id=user.id if user is not None else None,
            actor_ip=request.client.host if request.client else None,
            payload={
                "format": ext,
                "status_code": exc.status_code,
                "data_classification": getattr(
                    request.state, "data_classification", DATA_CLASSIFICATION_DEFAULT
                ),
            },
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except BaseException:
        # BackgroundTask only fires on the success path; clean up synchronously
        # on cancellation / unexpected errors. HTTPException is caught above.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    response_headers: dict[str, str] = {"X-Output-SHA256": output_hash}
    if target_result is not None:
        response_headers["X-FileMorph-Achieved-Bytes"] = str(target_result["achieved_bytes"])
        response_headers["X-FileMorph-Final-Quality"] = str(target_result["final_quality"])

    return FileResponse(
        output_path,
        media_type="application/octet-stream",
        filename=download_name,
        headers=response_headers,
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
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
        description="Target output size in KB. Applies to all files. JPEG/WebP only.",
    ),
    user: User | None = Depends(get_optional_user),
) -> Response:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded.")

    tier = tier_for(user)
    # NEU-D.1: same one-slot-per-batch policy as convert/batch.
    async with acquire_slot(actor_id=_actor_id(request, user), tier=tier):
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
                "Upgrade your plan for larger batches."
            ),
        )

    if target_size_kb is not None:
        target_bytes = target_size_kb * 1024
        if target_bytes > quota.output_cap_bytes:
            cap_kb = quota.output_cap_bytes // 1024
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Target size {target_size_kb} KB exceeds tier output cap of {cap_kb} KB. "
                    "Upgrade your plan for larger outputs."
                ),
            )

    _t0 = time.monotonic()
    results: list[BatchFileResult] = []
    # Aggregate per-key counts and flush once at the end — one UPSERT per
    # unique key instead of N round-trips for an N-file batch.
    metric_counts: dict[str, int] = {}

    for upload in files:
        original_stem = Path(upload.filename or "result").stem
        ext = Path(upload.filename or "").suffix.lstrip(".").lower()
        size_in = upload.size or 0
        out_name = safe_download_name(f"{original_stem}_compressed.{ext}")

        try:
            if not ext:
                raise ValueError("Cannot determine format from filename.")
            if ext not in IMAGE_FMTS and ext not in VIDEO_FMTS:
                raise ValueError(f"Compression not supported for '.{ext}'.")
            if size_in > quota.max_file_size_bytes:
                limit_mb = quota.max_file_size_bytes // (1024 * 1024)
                raise ValueError(f"File too large ({limit_mb} MB max for your plan).")

            tmp_dir = tempfile.mkdtemp(prefix="fm_")
            try:
                temp_stem = uuid.uuid4().hex
                input_path = Path(tmp_dir) / f"{temp_stem}.{ext}"
                output_path = Path(tmp_dir) / f"{temp_stem}_compressed.{ext}"

                with input_path.open("wb") as f:
                    shutil.copyfileobj(upload.file, f)

                with open(input_path, "rb") as f:
                    header = f.read(16)
                if any(header.startswith(sig) for sig in BLOCKED_MAGIC):
                    raise ValueError("File type not permitted.")

                if target_size_kb is not None:
                    if ext not in TARGET_SIZE_FORMATS:
                        raise ValueError(
                            "Target-size compression supports only JPEG and WebP. "
                            "Use quality= for PNG/TIFF."
                        )
                    await asyncio.to_thread(
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
                        compress_video, input_path, output_path, quality=effective_quality
                    )

                # S1-B: Output-cap check — reject before loading into memory.
                output_disk_size = output_path.stat().st_size
                if output_disk_size > quota.output_cap_bytes:
                    cap_mb = quota.output_cap_bytes // _MB
                    out_mb = output_disk_size // _MB
                    raise ValueError(
                        f"Output too large ({out_mb} MB > {cap_mb} MB cap). "
                        "Lower the quality or upgrade your plan."
                    )

                content = output_path.read_bytes()
                results.append(
                    BatchFileResult(
                        name=out_name,
                        status="ok",
                        size_in=size_in,
                        size_out=len(content),
                        content=content,
                    )
                )
                key = f"compress.{ext}"
                metric_counts[key] = metric_counts.get(key, 0) + 1
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except ValueError as e:
            results.append(
                BatchFileResult(
                    name=out_name, status="error", size_in=size_in, error_message=str(e)
                )
            )
            metric_counts["failures.compress"] = metric_counts.get("failures.compress", 0) + 1
        except Exception:
            logger.exception("Batch compression error on one file")
            results.append(
                BatchFileResult(
                    name=out_name,
                    status="error",
                    size_in=size_in,
                    error_message="Compression failed.",
                )
            )
            metric_counts["failures.compress"] = metric_counts.get("failures.compress", 0) + 1

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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=batch_error_response(results, summary),
        )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="filemorph-batch.zip"'},
    )
