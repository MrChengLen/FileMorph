import asyncio
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
from app.converters.base import UnsupportedConversionError
from app.converters.registry import _ensure_loaded, get_converter
from app.core.audit import record_event as audit_record
from app.core.batch import BatchFileResult, batch_error_response, build_batch_zip
from app.core.concurrency import acquire_slot
from app.core.data_classification import DEFAULT_CLASSIFICATION as DATA_CLASSIFICATION_DEFAULT
from app.core.metrics import increment as metric_increment
from app.core.processing import BLOCKED_MAGIC, actor_id, sha256_file
from app.core.quotas import _MB, get_quota, tier_for
from app.core.rate_limit import limiter
from app.core.usage import enforce_monthly_quota, record_usage
from app.core.utils import safe_download_name
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

# Trigger converter registration on module load
_ensure_loaded()


@router.post("/convert", tags=["Convert"], dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def convert_file(
    request: Request,
    file: UploadFile,
    target_format: str = Form(..., description="Target format, e.g. 'jpg', 'pdf', 'mp3'"),
    quality: int = Form(85, ge=1, le=100, description="Quality 1-100 (where applicable)"),
    user: User | None = Depends(get_optional_user),
) -> Response:
    tier = tier_for(user)
    async with acquire_slot(actor_id=actor_id(request, user), tier=tier):
        return await _do_convert(request, file, target_format, quality, user, tier)


async def _do_convert(
    request: Request,
    file: UploadFile,
    target_format: str,
    quality: int,
    user: User | None,
    tier: str,
) -> Response:
    src_ext = Path(file.filename or "").suffix.lstrip(".").lower()
    tgt_ext = target_format.strip().lower().lstrip(".")

    if not src_ext:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot determine source format from filename.",
        )

    try:
        converter = get_converter(src_ext, tgt_ext)
    except UnsupportedConversionError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    # Tier-based file size enforcement (anonymous: 20 MB, free: 50, pro: 100, business: 500)
    # ``tier`` is passed in from the wrapper that already acquired the
    # NEU-D.1 concurrency slot — keep it identical to the slot's tier
    # so cap-enforcement and capacity-accounting agree on who the
    # caller is.
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

    # PR-M: monthly API-call quota gate. Anonymous + Enterprise tiers
    # are exempt; everyone else runs against the limit defined in
    # app/core/quotas.py. Raises HTTPException(429) with Retry-After
    # set to the next month boundary when the limit is reached.
    await enforce_monthly_quota(user)

    # GDPR: keep original stem only for Content-Disposition, never as a filesystem path
    original_stem = Path(file.filename or "result").stem

    # A-1 + GDPR: UUID temp names — no PII on disk, no path traversal
    _t0 = time.monotonic()
    tmp_dir = tempfile.mkdtemp(prefix="fm_")
    try:
        temp_stem = uuid.uuid4().hex
        input_path = Path(tmp_dir) / f"{temp_stem}.{src_ext}"
        output_path = Path(tmp_dir) / f"{temp_stem}.{tgt_ext}"

        with input_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        input_size_bytes = input_path.stat().st_size

        # A-1: Magic-byte validation
        with open(input_path, "rb") as f:
            header = f.read(16)
        if any(header.startswith(sig) for sig in BLOCKED_MAGIC):
            raise HTTPException(status_code=400, detail="File type not permitted.")

        try:
            # Offload sync C-binding call (Pillow/FFmpeg/WeasyPrint/pypdf) to a
            # worker thread so the event-loop can serve parallel requests.
            await asyncio.to_thread(converter.convert, input_path, output_path, quality=quality)
        except HTTPException:
            raise
        except Exception:
            # A-3: Log full exception server-side, return generic message to client
            logger.exception("Conversion error: %s -> %s", src_ext, tgt_ext)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Conversion failed. Verify your file is valid and the format is supported.",
            )

        # S1-B: Output-cap check — reject before loading into memory. Guards
        # against bandwidth amplification (JPG→PNG ~5-10×, MP3→WAV ~11×).
        output_disk_size = output_path.stat().st_size
        if output_disk_size > quota.output_cap_bytes:
            cap_mb = quota.output_cap_bytes // _MB
            out_mb = output_disk_size // _MB
            if user is None:
                hint = "Try a more efficient target (WebP/AVIF for images, FLAC for audio) or register for a higher cap."
            else:
                hint = "Try a more efficient target (WebP/AVIF for images, FLAC for audio) or upgrade your plan."
            # S4-foundation: record the rejection so dashboards can count
            # cap-hits per tier / format-pair. Success log alone would miss
            # this outcome entirely.
            logger.info(
                "conversion rejected",
                extra={
                    "operation": "convert",
                    "reason": "output_cap",
                    "tier": tier,
                    "src_format": src_ext,
                    "tgt_format": tgt_ext,
                    "input_size_bytes": input_size_bytes,
                    "output_size_bytes": output_disk_size,
                    "cap_bytes": quota.output_cap_bytes,
                    "duration_ms": round((time.monotonic() - _t0) * 1000),
                    "success": False,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Output too large ({out_mb} MB > {cap_mb} MB cap). {hint}",
            )

        # S3: stream the output from disk instead of buffering into RAM. The
        # BackgroundTask runs after the response body is fully sent, so temp
        # cleanup is deferred but still guaranteed. On any error path below
        # (or above, before this block), the except handler cleans up sync.
        download_name = safe_download_name(f"{original_stem}.{tgt_ext}")
        output_size_bytes = output_disk_size

        # NEU-B.2: integrity hash for downstream auditors / eDiscovery /
        # GoBD-archival workflows. Cheap to compute (single pass over the
        # already-on-disk output, bounded by the quota cap), and gives the
        # caller a tamper-detection anchor without us having to keep the
        # file or sign it. Read in chunks so large outputs don't double
        # the memory footprint.
        output_hash = await asyncio.to_thread(sha256_file, output_path)
        amplification_ratio = (
            round(output_size_bytes / input_size_bytes, 3) if input_size_bytes > 0 else None
        )
        logger.info(
            "conversion complete",
            extra={
                "operation": "convert",
                "tier": tier,
                "src_format": src_ext,
                "tgt_format": tgt_ext,
                "input_size_bytes": input_size_bytes,
                "output_size_bytes": output_size_bytes,
                "file_size_bytes": output_size_bytes,  # legacy key kept for existing dashboards
                "amplification_ratio": amplification_ratio,
                "duration_ms": round((time.monotonic() - _t0) * 1000),
                "success": True,
            },
        )
        # S10-lite: per-format-pair counter for the cockpit. metric_increment
        # is fire-and-forget — no try/except needed (it swallows internally).
        # It opens its own session so a metrics failure can't corrupt the
        # request's transaction (and there is none here, but the principle
        # is what keeps batch + auth integrations safe).
        await metric_increment(f"convert.{src_ext}-to-{tgt_ext}")
        # NEU-B.1: tamper-evident audit trail. Same fire-and-forget shape as
        # the metric write; Compliance Edition flips ``audit_fail_closed``
        # so this raises and the request fails closed instead. The payload
        # carries no file content — only metadata sufficient for an
        # ISO 27001 A.12.4.1 / BORA §50 retrospective review.
        await audit_record(
            "convert.success",
            actor_user_id=user.id if user is not None else None,
            actor_ip=request.client.host if request.client else None,
            payload={
                "src": src_ext,
                "tgt": tgt_ext,
                "input_bytes": input_size_bytes,
                "output_bytes": output_size_bytes,
                "output_sha256": output_hash,
                "tier": tier,
                "data_classification": getattr(
                    request.state, "data_classification", DATA_CLASSIFICATION_DEFAULT
                ),
            },
        )
        # PR-M: record one row toward the monthly-quota counter. Anonymous
        # callers (no user_id) are skipped — there is no caller identity
        # to attribute the row to. Fire-and-forget; a failed insert logs
        # at WARNING but never breaks the request.
        await record_usage(
            user_id=user.id if user is not None else None,
            api_key_id=None,
            endpoint="convert",
            file_size_bytes=input_size_bytes,
            duration_ms=round((time.monotonic() - _t0) * 1000),
        )
    except HTTPException as exc:
        # Track conversion failures separately from infrastructure errors
        # so the cockpit can show a meaningful failure-rate. We swallow the
        # metric write itself — the user-visible exception still propagates.
        await metric_increment("failures.convert")
        await audit_record(
            "convert.failure",
            actor_user_id=user.id if user is not None else None,
            actor_ip=request.client.host if request.client else None,
            payload={
                "src": src_ext,
                "tgt": tgt_ext,
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
        # on any failure (cancellation, unexpected error). HTTPException is
        # handled above so we can also count the failure.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return FileResponse(
        output_path,
        media_type="application/octet-stream",
        filename=download_name,
        headers={"X-Output-SHA256": output_hash},
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )


@router.post("/convert/batch", tags=["Convert"], dependencies=[Depends(require_api_key)])
@limiter.limit("3/minute")
async def convert_batch(
    request: Request,
    files: list[UploadFile] = File(..., description="Files to convert (multi-upload)"),
    target_formats: list[str] = Form(
        ...,
        description="Target format per uploaded file, same order and length as `files`.",
    ),
    quality: int = Form(85, ge=1, le=100),
    user: User | None = Depends(get_optional_user),
) -> Response:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded.")

    tier = tier_for(user)
    # NEU-D.1: a batch counts as one concurrency slot — the per-file
    # work is sequential inside the route, so a 25-file batch holds
    # the slot for 25× the per-file cost. Per-file accounting would
    # double-charge against the per-actor cap and starve real second
    # requests. The slot lives long enough that the global cap
    # serialises bursts of large batches across users.
    async with acquire_slot(actor_id=actor_id(request, user), tier=tier):
        return await _do_convert_batch(request, files, target_formats, quality, user, tier)


async def _do_convert_batch(
    request: Request,
    files: list[UploadFile],
    target_formats: list[str],
    quality: int,
    user: User | None,
    tier: str,
) -> Response:
    quota = get_quota(tier)
    if len(files) > quota.max_files_per_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Batch size {len(files)} exceeds tier limit of {quota.max_files_per_batch}. "
                "Upgrade your plan for larger batches."
            ),
        )

    # Mixed-format batches send one target per input file. The Web UI renders
    # a per-row dropdown; CLI callers pass repeated `target_formats` form keys
    # (e.g. `-F target_formats=pdf -F target_formats=pdf`). Mismatched length
    # is a client bug — reject before we touch disk.
    if len(target_formats) != len(files):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"target_formats has {len(target_formats)} entries but {len(files)} files "
                "were uploaded. One target per file is required."
            ),
        )

    # PR-M: monthly quota gate. One batch counts as one API call (matches the
    # pricing-page wording). Same gate is also at the top of single /convert.
    await enforce_monthly_quota(user)

    _t0 = time.monotonic()
    results: list[BatchFileResult] = []
    # Aggregate per-key counts for the post-loop metrics flush. One UPSERT
    # per unique key (typically 1-3) instead of N round-trips for an N-file
    # batch — keeps a 100-file batch from hammering the metrics table.
    metric_counts: dict[str, int] = {}

    for upload, raw_target in zip(files, target_formats):
        tgt_ext = raw_target.strip().lower().lstrip(".")
        original_stem = Path(upload.filename or "result").stem
        src_ext = Path(upload.filename or "").suffix.lstrip(".").lower()
        size_in = upload.size or 0
        out_name = safe_download_name(f"{original_stem}.{tgt_ext}")

        try:
            if not src_ext:
                raise ValueError("Cannot determine source format from filename.")
            if size_in > quota.max_file_size_bytes:
                limit_mb = quota.max_file_size_bytes // (1024 * 1024)
                raise ValueError(f"File too large ({limit_mb} MB max for your plan).")
            converter = get_converter(src_ext, tgt_ext)

            tmp_dir = tempfile.mkdtemp(prefix="fm_")
            try:
                temp_stem = uuid.uuid4().hex
                input_path = Path(tmp_dir) / f"{temp_stem}.{src_ext}"
                output_path = Path(tmp_dir) / f"{temp_stem}.{tgt_ext}"

                with input_path.open("wb") as f:
                    shutil.copyfileobj(upload.file, f)

                with open(input_path, "rb") as f:
                    header = f.read(16)
                if any(header.startswith(sig) for sig in BLOCKED_MAGIC):
                    raise ValueError("File type not permitted.")

                await asyncio.to_thread(converter.convert, input_path, output_path, quality=quality)

                # S1-B: Output-cap check — reject before loading into memory.
                output_disk_size = output_path.stat().st_size
                if output_disk_size > quota.output_cap_bytes:
                    cap_mb = quota.output_cap_bytes // _MB
                    out_mb = output_disk_size // _MB
                    raise ValueError(
                        f"Output too large ({out_mb} MB > {cap_mb} MB cap). "
                        "Try WebP/AVIF or upgrade your plan."
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
                key = f"convert.{src_ext}-to-{tgt_ext}"
                metric_counts[key] = metric_counts.get(key, 0) + 1
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except UnsupportedConversionError as e:
            results.append(
                BatchFileResult(
                    name=out_name, status="error", size_in=size_in, error_message=str(e)
                )
            )
            metric_counts["failures.convert"] = metric_counts.get("failures.convert", 0) + 1
        except ValueError as e:
            results.append(
                BatchFileResult(
                    name=out_name, status="error", size_in=size_in, error_message=str(e)
                )
            )
            metric_counts["failures.convert"] = metric_counts.get("failures.convert", 0) + 1
        except Exception:
            logger.exception("Batch conversion error on one file")
            results.append(
                BatchFileResult(
                    name=out_name,
                    status="error",
                    size_in=size_in,
                    error_message="Conversion failed.",
                )
            )
            metric_counts["failures.convert"] = metric_counts.get("failures.convert", 0) + 1

    # Flush aggregated counters — one UPSERT per unique key, all on isolated
    # sessions so a metrics failure can't poison the response.
    for key, count in metric_counts.items():
        await metric_increment(key, by=count)

    duration_ms = round((time.monotonic() - _t0) * 1000)
    zip_bytes, summary = build_batch_zip(results, operation="convert", duration_ms=duration_ms)
    rejected_output_cap = sum(
        1 for r in results if r.status == "error" and "Output too large" in (r.error_message or "")
    )
    logger.info(
        "batch convert complete",
        extra={
            "operation": "convert_batch",
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

    # PR-M: one row per HTTP call (not per-file inside the batch) — matches
    # the pricing-page wording "API calls per month". File-level counts go
    # into the metrics table for the cockpit.
    await record_usage(
        user_id=user.id if user is not None else None,
        api_key_id=None,
        endpoint="convert/batch",
        file_size_bytes=sum(r.size_in for r in results),
        duration_ms=duration_ms,
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="filemorph-batch.zip"'},
    )
