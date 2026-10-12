"""Optional shared API-key protection for business endpoints."""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from backend.core.config import settings


async def require_api_access(request: Request) -> None:
    """Require a configured key for /api endpoints while keeping probes separate."""
    key = settings.api_key
    if key is None or not request.url.path.startswith("/api/"):
        return
    expected = key.get_secret_value()
    if not expected:
        return
    supplied = request.headers.get("X-API-Key", "")
    if not supplied:
        scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer":
            supplied = credential
    if not supplied or not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
