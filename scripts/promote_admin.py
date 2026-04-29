#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Promote a registered user to the ``admin`` role.

Usage::

    python scripts/promote_admin.py <email>

Designed to be run inside the production container::

    docker compose exec <app-service> python scripts/promote_admin.py <email>

Phase 1 has no cockpit UI for promoting a new admin. The only recovery path
after accidentally demoting the last admin is re-running this CLI on the
server. Keep that in mind when editing the user table.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.base import AsyncSessionLocal, engine
from app.db.models import RoleEnum, User


async def _promote(email: str) -> int:
    if AsyncSessionLocal is None or engine is None:
        print("DATABASE_URL is not configured; cannot connect.", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            print(f"No user with email {email!r} found.", file=sys.stderr)
            return 1

        if user.role == RoleEnum.admin:
            print(f"{email} is already an admin (no change).")
            return 0

        previous = user.role.value
        user.role = RoleEnum.admin
        await session.commit()
        print(f"Promoted {email}: {previous} → admin")
        return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/promote_admin.py <email>", file=sys.stderr)
        return 64
    return asyncio.run(_promote(sys.argv[1].strip()))


if __name__ == "__main__":
    sys.exit(main())
