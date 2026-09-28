# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.rate_limit import account_or_ip, limiter
from app.db.base import get_db
from app.db.models import ApiKey, User

router = APIRouter(prefix="/keys", tags=["API Keys"])

# Active keys per account. A revoked key stays as an inactive row (usage
# records point at it), so this caps what is live; the rate limit on
# ``POST /keys`` bounds how fast revoke-and-recreate can add rows.
MAX_ACTIVE_KEYS = 25


class KeyResponse(BaseModel):
    id: str
    label: str
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool


class CreateKeyResponse(KeyResponse):
    key: str


class CreateKeyRequest(BaseModel):
    label: str = Field("My API Key", max_length=100)


@router.post("", response_model=CreateKeyResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute", key_func=account_or_ip)
async def create_key(
    request: Request,
    body: CreateKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(func.count(ApiKey.id)).where(ApiKey.user_id == user.id, ApiKey.is_active.is_(True))
    )
    if int(result.scalar_one()) >= MAX_ACTIVE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"API key limit reached ({MAX_ACTIVE_KEYS} active keys). "
                "Revoke a key you no longer use, then create a new one."
            ),
        )
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(user_id=user.id, key_hash=key_hash, label=body.label)
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return CreateKeyResponse(
        id=str(api_key.id),
        label=api_key.label,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        is_active=api_key.is_active,
        key=raw_key,
    )


@router.get("", response_model=list[KeyResponse])
@limiter.limit("120/minute", key_func=account_or_ip)
async def list_keys(
    request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.is_active.is_(True))
    )
    return [
        KeyResponse(
            id=str(k.id),
            label=k.label,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            is_active=k.is_active,
        )
        for k in result.scalars().all()
    ]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute", key_func=account_or_ip)
async def delete_key(
    request: Request,
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.user_id == user.id, ApiKey.is_active.is_(True)
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    key.is_active = False
    await db.commit()
