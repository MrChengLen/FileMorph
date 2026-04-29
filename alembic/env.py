# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alembic environment — async-aware, reads ``DATABASE_URL`` from env/settings.

``sqlalchemy.url`` in ``alembic.ini`` is deliberately empty; the URL is pulled
at runtime from :data:`app.core.config.settings` so there is exactly one
source of truth for connection strings.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import Base and all models so Base.metadata is fully populated.
from app.db.base import Base
import app.db.models  # noqa: F401 — side-effect import to register tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        try:
            from app.core.config import settings

            url = getattr(settings, "database_url", "") or ""
        except Exception:
            url = ""
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set; Alembic cannot run without a connection string."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL to stdout)."""
    context.configure(
        url=_resolve_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode with an async engine."""
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _resolve_database_url()

    connectable = async_engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
