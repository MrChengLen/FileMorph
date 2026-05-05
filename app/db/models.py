# SPDX-License-Identifier: AGPL-3.0-or-later
"""ORM models for the FileMorph database schema (C-1)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from datetime import date as date_type

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TierEnum(str, enum.Enum):
    free = "free"
    pro = "pro"
    business = "business"
    enterprise = "enterprise"


class RoleEnum(str, enum.Enum):
    user = "user"
    admin = "admin"


class JobStatusEnum(str, enum.Enum):
    processing = "processing"
    done = "done"
    error = "error"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[TierEnum] = mapped_column(
        Enum(TierEnum, name="tier_enum"), nullable=False, default=TierEnum.free
    )
    role: Mapped[RoleEnum] = mapped_column(
        Enum(RoleEnum, name="role_enum"),
        nullable=False,
        default=RoleEnum.user,
        server_default=RoleEnum.user.value,
    )
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    api_keys: Mapped[list[ApiKey]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    file_jobs: Mapped[list[FileJob]] = relationship("FileJob", back_populates="user")
    usage_records: Mapped[list[UsageRecord]] = relationship("UsageRecord", back_populates="user")

    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_created_at", "created_at"),
        Index("ix_users_role", "role"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 hex digest of the raw key"
    )
    label: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="api_keys")
    usage_records: Mapped[list[UsageRecord]] = relationship("UsageRecord", back_populates="api_key")

    __table_args__ = (Index("ix_api_keys_key_hash", "key_hash"),)


class FileJob(Base):
    __tablename__ = "file_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    source_format: Mapped[str] = mapped_column(String, nullable=False)
    target_format: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, comment="S3/R2 object key; NULL = ephemeral"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[JobStatusEnum] = mapped_column(
        Enum(JobStatusEnum, name="job_status_enum"),
        nullable=False,
        default=JobStatusEnum.processing,
    )

    # Relationships
    user: Mapped[Optional[User]] = relationship("User", back_populates="file_jobs")


class UsageRecord(Base):
    __tablename__ = "usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
    )
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    user: Mapped[Optional[User]] = relationship("User", back_populates="usage_records")
    api_key: Mapped[Optional[ApiKey]] = relationship("ApiKey", back_populates="usage_records")


class DailyMetric(Base):
    """Per-day, per-key counter — S10-lite analytics aggregation surface.

    Composite primary key ``(date, metric_key)`` plus a ``count`` column. One
    row per (day, metric) regardless of traffic volume — atomic UPSERT in
    ``app.core.metrics.increment`` keeps it that way.

    Examples of ``metric_key``:

    - ``page_views`` — every GET to a non-API, non-static path
    - ``convert.jpg-to-pdf`` — successful conversion per format-pair
    - ``compress.jpg`` — successful compression per format
    - ``registrations`` — successful new-user registrations
    - ``failures.convert`` — failed conversions (any cause)

    Counters are not personal data: they're aggregates, comparable to standard
    web-server access-log roll-ups, so no Privacy-Policy update or DSGVO Art. 13
    notice is required for shipping this. Self-hosters who don't want the
    counters at all can set ``METRICS_ENABLED=false``.
    """

    __tablename__ = "daily_metrics"

    date: Mapped[date_type] = mapped_column(Date, primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (Index("ix_daily_metrics_metric_key", "metric_key"),)
