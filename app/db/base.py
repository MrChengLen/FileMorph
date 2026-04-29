# SPDX-License-Identifier: AGPL-3.0-or-later
"""
SQLAlchemy async engine and session factory.
Requires DATABASE_URL env var (postgresql+asyncpg://user:pass@host/db).
When DATABASE_URL is not set, the database layer is disabled (Community Edition mode).
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL")
# pool_pre_ping: re-check a pooled connection before handing it out, so stale
# connections (killed by Postgres idle-timeout, network blip, failover) don't
# surface as mid-request errors.
# pool_recycle: force-close and replace any pooled connection older than 1 h,
# which keeps us ahead of Postgres/Hetzner cloud idle-kill timers.
engine = (
    create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True, pool_recycle=3600)
    if DATABASE_URL
    else None
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False) if engine else None


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Yields None if database is not configured."""
    if AsyncSessionLocal is None:
        yield None  # type: ignore[misc]
        return
    async with AsyncSessionLocal() as session:
        yield session
