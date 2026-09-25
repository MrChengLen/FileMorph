# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import hmac
import json
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import ApiKey


def _keys_path() -> Path:
    return Path(settings.api_keys_file)


def _load_hashes() -> list[str]:
    path = _keys_path()
    if not path.exists():
        return []
    with path.open() as f:
        data = json.load(f)
    return data.get("keys", [])


def _save_hashes(hashes: list[str]) -> None:
    path = _keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump({"keys": hashes}, f, indent=2)


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key, store its hash, and return the plaintext key."""
    key = secrets.token_urlsafe(32)
    hashes = _load_hashes()
    hashes.append(_hash_key(key))
    _save_hashes(hashes)
    return key


def validate_api_key(key: str) -> bool:
    """Return True if the key's hash matches any stored hash (constant-time)."""
    key_hash = _hash_key(key)
    valid = False
    for stored in _load_hashes():
        # hmac.compare_digest is constant-time; loop never short-circuits
        if hmac.compare_digest(key_hash, stored):
            valid = True
    return valid


async def find_active_api_key(db: AsyncSession, key: str) -> ApiKey | None:
    """Return the dashboard-minted ``ApiKey`` for ``key`` with its owner
    loaded, or ``None`` if it is unknown, revoked, or the owner is
    deactivated or deleted.

    These keys live in the DB ``api_keys`` table, not the file store above,
    and are looked up by SHA-256 digest rather than compared in constant
    time: a timing leak could reveal at most a stored digest, useless without
    a preimage of a 256-bit random key.
    """
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.key_hash == _hash_key(key), ApiKey.is_active.is_(True))
        .options(selectinload(ApiKey.user))
    )
    api_key = result.scalar_one_or_none()
    owner = api_key.user if api_key else None
    # ``deleted_at`` is defence-in-depth, as in ``get_current_user``.
    if owner is not None and owner.is_active and owner.deleted_at is None:
        return api_key
    return None


def revoke_api_key(key: str) -> bool:
    """Remove a key by its hash. Returns True if the key was found and removed."""
    key_hash = _hash_key(key)
    hashes = _load_hashes()
    if key_hash not in hashes:
        return False
    hashes.remove(key_hash)
    _save_hashes(hashes)
    return True
