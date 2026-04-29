from fastapi import Header, HTTPException, status

from app.core.security import validate_api_key


async def require_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")) -> str | None:
    """Validate X-API-Key if provided; allow through if absent (web UI public access)."""
    if x_api_key is None:
        return None
    if not validate_api_key(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    return x_api_key
