# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import APIRouter, Request

from app.compressors.image import _SUPPORTED_FORMATS as IMAGE_COMPRESS_FMTS
from app.compressors.video import _SUPPORTED_FORMATS as VIDEO_COMPRESS_FMTS
from app.converters.registry import get_supported_conversions
from app.core.rate_limit import limiter
from app.models.schemas import FormatsResponse

router = APIRouter()


@router.get("/formats", response_model=FormatsResponse, tags=["Formats"])
@limiter.limit("120/minute")
async def list_formats(request: Request) -> FormatsResponse:
    return FormatsResponse(
        conversions=get_supported_conversions(),
        compression={
            "image": IMAGE_COMPRESS_FMTS,
            "video": VIDEO_COMPRESS_FMTS,
        },
    )
