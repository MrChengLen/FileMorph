# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.db.base import get_db
from app.db.models import ApiKey, User

router = APIRouter(prefix="/keys", tags=["API Keys"])


class KeyResponse(BaseModel):
    id: str
    label: str
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool


class CreateKeyResponse(KeyResponse):
    key: str


class CreateKeyRequest(BaseModel):
    label: str = "My API Key"


@router.post("", response_model=CreateKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: CreateKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
async def list_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
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
async def delete_key(
    key_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
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
